"""
Marketplace data layer and install operations for cozy-kit plugins.

Public API
----------
fetch_index(force_refresh)      -> List[dict]   all known plugins (cached, TTL 1h)
search_plugins(query, index)    -> List[dict]   subset matching query
get_index_entry(name)           -> dict | None  single entry from the cached index
get_plugin_pypi_info(name)      -> dict         full live PyPI metadata for one plugin
check_updates()                 -> List[dict]   installed plugins with newer versions
install_from_marketplace(...)   -> PluginManifest

Index entry shape
-----------------
{
  "package":     "cozy-kit-plugin-fancy-greetings",  # full PyPI name
  "name":        "fancy-greetings",                  # short hyphen name
  "plugin_name": "fancy_greetings",                  # Python identifier
  "version":     "1.0.0",                            # from PyPI search
  "description": "...",
  "author":      "...",     # from registry; "" when PyPI-only
  "license":     "MIT",     # from registry; "" when PyPI-only
  "target":      "Greeting",# from registry; "" when PyPI-only
  "tags":        ["greeting", "emoji"],  # from registry; [] when PyPI-only
  "verified":    True,      # curated flag; False when PyPI-only
}
"""

import importlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cozy_kit._internal.errors.plugin_errors import MarketplaceError

_PREFIX = "cozy-kit-plugin-"
_CACHE_TTL = 3600  # seconds

# Curated registry hosted in a dedicated GitHub repo.
# Plugin authors submit a PR to add or update their entry.
_REGISTRY_URL = (
    "https://raw.githubusercontent.com/youssefahmed2017/"
    "cozy-kit-marketplace/main/marketplace.json"
)


# ── name helpers ──────────────────────────────────────────────────────────────


def _short_name(package: str) -> str:
    """'cozy-kit-plugin-fancy-greetings' → 'fancy-greetings'"""
    return package[len(_PREFIX) :] if package.startswith(_PREFIX) else package


def _plugin_name(package: str) -> str:
    """'cozy-kit-plugin-fancy-greetings' → 'fancy_greetings'"""
    return _short_name(package).replace("-", "_")


# ── PyPI helpers ──────────────────────────────────────────────────────────────


def _pypi_search_raw(query: str) -> List[Dict]:
    """
    Scrape the PyPI search results page for *query*.
    Returns a list of {name, version, description} dicts.
    """
    import html.parser
    import urllib.parse
    import urllib.request

    class _SnippetParser(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.results: List[Dict] = []
            self._in_snippet = False
            self._depth = 0
            self._pkg: Dict = {}
            self._capture: Optional[str] = None

        def handle_starttag(self, tag, attrs):
            classes = dict(attrs).get("class", "")
            if not self._in_snippet:
                if tag == "a" and "package-snippet" in classes:
                    self._in_snippet = True
                    self._depth = 0
                    self._pkg = {}
                    self._capture = None
            else:
                self._depth += 1
                if tag in ("span", "p"):
                    for cls in classes.split():
                        if cls.startswith("package-snippet__"):
                            self._capture = cls[len("package-snippet__") :]
                            break

        def handle_endtag(self, tag):
            if not self._in_snippet:
                return
            if tag == "a" and self._depth == 0:
                if self._pkg.get("name"):
                    self.results.append(dict(self._pkg))
                self._in_snippet = False
                self._capture = None
                return
            if tag in ("span", "p"):
                self._capture = None
            if self._depth > 0:
                self._depth -= 1

        def handle_data(self, data):
            if not (self._in_snippet and self._capture):
                return
            text = data.strip()
            if text:
                prev = self._pkg.get(self._capture, "")
                self._pkg[self._capture] = (prev + " " + text).strip() if prev else text

    url = "https://pypi.org/search/?" + urllib.parse.urlencode({"q": query, "o": ""})
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "cozy-plugins/1.0",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise MarketplaceError(f"Could not reach PyPI: {exc}") from exc

    parser = _SnippetParser()
    parser.feed(body)
    return parser.results


def _pypi_json_info(package: str) -> Dict:
    """
    Fetch full metadata for *package* from the PyPI JSON API.
    Raises MarketplaceError on 404 or network failure.
    """
    import urllib.error
    import urllib.request

    url = f"https://pypi.org/pypi/{package}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "cozy-plugins/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())["info"]
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MarketplaceError(
                f"'{package}' was not found on PyPI. "
                "Check that the short name is correct "
                "(e.g. 'fancy-greetings' for 'cozy-kit-plugin-fancy-greetings')."
            ) from exc
        raise MarketplaceError(
            f"PyPI returned HTTP {exc.code} for '{package}'."
        ) from exc
    except MarketplaceError:
        raise
    except Exception as exc:
        raise MarketplaceError(f"Could not reach PyPI: {exc}") from exc


# ── registry ─────────────────────────────────────────────────────────────────


def _fetch_from_registry() -> List[Dict]:
    """
    Fetch the curated plugin list from the GitHub registry.

    Returns normalised index entries (version field left empty — filled later
    by merging with PyPI search results).
    Raises on any network or parse error so the caller can fall back to PyPI.
    """
    import urllib.request

    req = urllib.request.Request(
        _REGISTRY_URL, headers={"User-Agent": "cozy-plugins/1.0"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    entries: List[Dict] = []
    for p in data.get("plugins", []):
        # Registry stores plugin_name (e.g. "fancy_greetings").
        # Derive the package name if not explicitly listed.
        plugin_name_field = p.get("name", "")
        package = p.get("package") or f"{_PREFIX}{plugin_name_field.replace('_', '-')}"
        entries.append(
            {
                "package": package,
                "name": _short_name(package),
                "plugin_name": _plugin_name(package),
                "version": "",  # filled from PyPI
                "description": p.get("description", ""),
                "author": p.get("author", ""),
                "license": p.get("license", ""),
                "target": p.get("target", ""),
                "tags": p.get("tags", []),
                "verified": bool(p.get("verified", False)),
                "builtin": bool(p.get("builtin", False)),
            }
        )
    return entries


# ── cache layer ───────────────────────────────────────────────────────────────


def _cache_path() -> Path:
    import os

    base = os.environ.get("COZY_KIT_PLUGINS_DIR")
    root = Path(base) if base else Path.home() / ".cozy_kit"
    return root / "marketplace_cache.json"


def _is_cache_fresh(data: Dict) -> bool:
    try:
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        return age < _CACHE_TTL
    except Exception:
        return False


def _load_cache() -> Optional[Dict]:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(plugins: List[Dict]) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "plugins": plugins,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass  # non-fatal


# ── public data API ───────────────────────────────────────────────────────────


def fetch_index(force_refresh: bool = False) -> List[Dict]:
    """
    Return the combined plugin index.

    Primary:  curated GitHub registry  → rich metadata (tags, verified, target, author, license)
    Versions: PyPI search              → always fresh, one request
    Fallback: PyPI search alone        → if the registry is unreachable

    Results are cached at ~/.cozy_kit/marketplace_cache.json (TTL = 1 hour).
    Raises MarketplaceError only when both sources are unreachable.
    """
    if not force_refresh:
        cached = _load_cache()
        if cached and _is_cache_fresh(cached):
            return cached.get("plugins", [])

    # ── registry ──────────────────────────────────────────────────────────────
    registry_by_pkg: Dict[str, Dict] = {}
    try:
        for entry in _fetch_from_registry():
            registry_by_pkg[entry["package"]] = entry
    except Exception:
        pass  # registry unavailable — proceed with PyPI only

    # ── PyPI search (versions + any uncurated packages) ───────────────────────
    pypi_error: Optional[Exception] = None
    pypi_by_pkg: Dict[str, Dict] = {}
    try:
        hits = _pypi_search_raw("cozy-kit-plugin")
        pypi_by_pkg = {
            h["name"]: h for h in hits if h.get("name", "").startswith(_PREFIX)
        }
    except MarketplaceError as exc:
        pypi_error = exc

    if not registry_by_pkg and pypi_error:
        raise MarketplaceError(
            "Could not reach the plugin registry or PyPI. "
            "Check your internet connection."
        )

    # ── merge ─────────────────────────────────────────────────────────────────
    plugins: List[Dict] = []
    seen: set = set()

    # Curated entries: registry metadata + version from PyPI search.
    # Fall back to the JSON API for any entry the search didn't return yet
    # (newly published packages can take hours to appear in search results).
    for pkg, entry in registry_by_pkg.items():
        seen.add(pkg)
        pypi = pypi_by_pkg.get(pkg, {})
        version = pypi.get("version", "")
        if not version:
            try:
                version = _pypi_json_info(pkg).get("version", "")
            except MarketplaceError:
                pass
        plugins.append(
            {
                **entry,
                "version": version,
                "description": entry["description"]
                or pypi.get("description", "").strip(),
            }
        )

    # PyPI-only packages not yet in the curated registry
    for pkg, hit in pypi_by_pkg.items():
        if pkg not in seen:
            plugins.append(
                {
                    "package": pkg,
                    "name": _short_name(pkg),
                    "plugin_name": _plugin_name(pkg),
                    "version": hit.get("version", ""),
                    "description": hit.get("description", "").strip(),
                    "author": "",
                    "license": "",
                    "target": "",
                    "tags": [],
                    "verified": False,
                }
            )

    _save_cache(plugins)
    return plugins


def search_plugins(query: str, index: Optional[List[Dict]] = None) -> List[Dict]:
    """
    Return index entries matching *query* (case-insensitive).
    Ranking: name match (0) > tag match (1) > description match (2).
    """
    if index is None:
        index = fetch_index()

    q = query.lower()
    ranked: List[Tuple[int, Dict]] = []
    for entry in index:
        in_name = (
            q in entry.get("name", "").lower()
            or q in entry.get("plugin_name", "").lower()
        )
        in_tags = any(q in t.lower() for t in entry.get("tags", []))
        in_desc = q in entry.get("description", "").lower()

        if in_name:
            ranked.append((0, entry))
        elif in_tags:
            ranked.append((1, entry))
        elif in_desc:
            ranked.append((2, entry))

    ranked.sort(key=lambda t: t[0])
    return [e for _, e in ranked]


def get_index_entry(name: str) -> Optional[Dict]:
    """
    Return the cached index entry for a plugin by short name or full package name.
    Returns None if the plugin is not in the index or the index cannot be fetched.
    """
    short = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    target_plugin_name = short.replace("-", "_")
    try:
        index = fetch_index()
    except MarketplaceError:
        return None
    for entry in index:
        if entry["plugin_name"] == target_plugin_name or entry["name"] == short:
            return entry
    return None


def get_plugin_pypi_info(name: str) -> Dict:
    """
    Return full PyPI metadata for a plugin by short name or full package name.
    Always fetches live data — no cache.
    """
    short = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    return _pypi_json_info(f"{_PREFIX}{short}")


def check_updates() -> List[Dict]:
    """
    Compare each registered plugin's version against the latest on PyPI.

    Returns a list of {name, package, installed, latest} dicts for every
    registered plugin that has a newer version available in the index.
    """
    from packaging.version import InvalidVersion, Version
    from cozy_kit.plugins.core.registry import get_registry

    registry = get_registry()
    if not registry:
        return []

    index = fetch_index()
    by_plugin_name = {e["plugin_name"]: e for e in index}

    outdated = []
    for plugin_name, info in registry.items():
        entry = by_plugin_name.get(plugin_name)
        if entry is None:
            continue
        installed_str = info.get("version", "0")
        latest_str = entry.get("version", "0")
        try:
            if Version(latest_str) > Version(installed_str):
                outdated.append(
                    {
                        "name": plugin_name,
                        "package": entry["package"],
                        "installed": installed_str,
                        "latest": latest_str,
                    }
                )
        except InvalidVersion:
            continue

    return outdated


# ── install / upgrade (Phase 2 + upgrade) ────────────────────────────────────


def _pip_install(package: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", package],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise MarketplaceError(
            f"pip install failed for '{package}':\n{result.stderr.strip()}"
        )


def _pip_upgrade(package: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", package],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise MarketplaceError(
            f"pip install --upgrade failed for '{package}':\n{result.stderr.strip()}"
        )


def _get_plugin_paths(module_name: str) -> Tuple[str, str]:
    """
    Import the freshly installed plugin package and return (METADATA, ENGINE).
    The package must expose these as string attributes in its __init__.py.
    """
    importlib.invalidate_caches()
    sys.modules.pop(module_name, None)

    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        raise MarketplaceError(
            f"Could not import '{module_name}' after installation. "
            "Make sure the package exposes METADATA and ENGINE in its __init__.py."
        ) from exc

    metadata = getattr(mod, "METADATA", None)
    engine = getattr(mod, "ENGINE", None)
    missing = [a for a, v in (("METADATA", metadata), ("ENGINE", engine)) if v is None]
    if missing:
        raise MarketplaceError(
            f"'{module_name}.__init__' is missing: {missing}. "
            "The plugin package must define METADATA and ENGINE path strings."
        )

    return str(metadata), str(engine)


def upgrade_from_marketplace(name: str):
    """
    Upgrade an installed marketplace plugin to the latest version on PyPI.

    Normalises *name* — all three forms are accepted:
      'fancy-greetings', 'fancy_greetings', 'cozy-kit-plugin-fancy-greetings'

    Steps:
      1. Verify the plugin is already registered (fail fast, no pip touch).
      2. pip install --upgrade <package>
      3. Re-import the package to get fresh METADATA + ENGINE paths.
      4. upgrade_plugin() — atomic: disable old → re-register → re-enable new.
         Fires on_disable (old engine) → on_update → on_enable (new engine).

    Returns the new PluginManifest.
    Raises PluginNotFoundError if not registered, MarketplaceError on pip/import
    failure, or any PluginSystemError subclass from the upgrade step.
    """
    from cozy_kit.plugins.core.installer import upgrade_plugin
    from cozy_kit.plugins.core.registry import get_registry
    from cozy_kit._internal.errors.plugin_errors import PluginNotFoundError

    stripped = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    short_name = stripped.replace("_", "-")  # canonical hyphen form
    package = f"{_PREFIX}{short_name}"
    module_name = package.replace("-", "_")
    plugin_name = short_name.replace("-", "_")  # registry key

    if plugin_name not in get_registry():
        raise PluginNotFoundError(
            f"'{plugin_name}' is not registered. "
            f"Install it first with: cozy-plugins marketplace install {short_name}"
        )

    _pip_upgrade(package)
    metadata_path, engine_path = _get_plugin_paths(module_name)
    return upgrade_plugin(name=plugin_name, metadata=metadata_path, engine=engine_path)


def install_from_marketplace(
    name: str,
    overwrite: bool = False,
    autoload: bool = True,
):
    """
    Install a cozy-kit plugin from PyPI by its short name.

    'fancy-greetings' and 'cozy-kit-plugin-fancy-greetings' are both accepted.

    Always runs pip install (adds/updates the package on disk).
    Registration only happens when the plugin is not already in the registry.
    If it is already registered, the PyPI package is still updated on disk and
    the caller receives None — run `upgrade_from_marketplace` to also update
    the cozy-kit registration.
    """
    from cozy_kit.plugins.core.publisher import plugin
    from cozy_kit.plugins.core.registry import get_registry, set_autoload

    short_name = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    package = f"{_PREFIX}{short_name}"
    module_name = package.replace("-", "_")
    plugin_name = short_name.replace("-", "_")

    _pypi_json_info(package)  # existence check — raises MarketplaceError on 404
    _pip_install(package)

    if plugin_name in get_registry() and not overwrite:
        # Package files updated on disk; registration untouched.
        return None

    metadata_path, engine_path = _get_plugin_paths(module_name)
    manifest = plugin(metadata=metadata_path, engine=engine_path, overwrite=overwrite)

    if autoload:
        set_autoload(manifest.name, True)

    return manifest
