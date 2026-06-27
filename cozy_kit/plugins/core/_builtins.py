"""Auto-install built-in plugins from the marketplace on first use."""

import json
import logging
from pathlib import Path

_log = logging.getLogger("cozy_kit.plugins.builtins")

_FLAG_FILE_NAME = ".builtins_installed"


def _flag_path() -> Path:
    import os
    base = os.environ.get("COZY_KIT_PLUGINS_DIR")
    root = Path(base) if base else Path.home() / ".cozy_kit"
    return root / _FLAG_FILE_NAME


def _installed_set() -> set:
    flag = _flag_path()
    if not flag.exists():
        return set()
    try:
        data = json.loads(flag.read_text(encoding="utf-8"))
        return set(data.get("installed", []))
    except Exception:
        return set()


def _mark_installed(plugin_names: list) -> None:
    flag = _flag_path()
    flag.parent.mkdir(parents=True, exist_ok=True)
    existing = _installed_set()
    existing.update(plugin_names)
    flag.write_text(
        json.dumps({"installed": sorted(existing)}, indent=2),
        encoding="utf-8",
    )


def ensure_builtins_installed(silent: bool = True) -> None:
    """
    Fetch the marketplace index and auto-install any built-in plugins that
    haven't been installed yet. Runs silently by default so import-time
    failures don't crash the calling code.

    The flag file (~/.cozy_kit/.builtins_installed) tracks which plugins have
    already been installed. New built-in plugins added to the marketplace will
    be picked up the next time this runs.
    """
    try:
        from cozy_kit.plugins.core.marketplace import fetch_index
        from cozy_kit.plugins.core.registry import get_registry
        from cozy_kit.plugins.core.marketplace import install_from_marketplace

        index = fetch_index()
        builtin_entries = [e for e in index if e.get("builtin")]
        if not builtin_entries:
            return

        already_done = _installed_set()
        registry = get_registry()
        newly_installed: list = []

        for entry in builtin_entries:
            pkg_name = entry.get("name", "")
            plugin_name = entry.get("plugin_name", "")
            if not pkg_name:
                continue

            if plugin_name in already_done:
                continue

            if plugin_name not in registry:
                _log.info("Auto-installing built-in plugin '%s'.", pkg_name)
                try:
                    install_from_marketplace(pkg_name)
                    newly_installed.append(plugin_name)
                except Exception as exc:
                    _log.warning(
                        "Could not auto-install built-in plugin '%s': %s",
                        pkg_name,
                        exc,
                    )
            else:
                newly_installed.append(plugin_name)

        if newly_installed:
            _mark_installed(newly_installed)

    except Exception as exc:
        if not silent:
            raise
        _log.debug("Built-in auto-install skipped: %s", exc)
