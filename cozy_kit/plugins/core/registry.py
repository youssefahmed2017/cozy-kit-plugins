from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from cozy_kit.plugins.models.manifest import PluginManifest
from cozy_kit._internal.errors.plugin_errors import PluginNotFoundError

_log = logging.getLogger("cozy_kit.plugins.registry")


def _plugins_dir() -> Path:
    override = os.environ.get("COZY_KIT_PLUGINS_DIR")
    return Path(override) if override else Path.home() / ".cozy_kit" / "plugins"


def _registry_file() -> Path:
    return _plugins_dir() / "registry.json"


def _autoload_file() -> Path:
    return _plugins_dir() / "autoload.json"


def _ensure_store():
    _plugins_dir().mkdir(parents=True, exist_ok=True)
    rf = _registry_file()
    if not rf.exists():
        rf.write_text(json.dumps({}), encoding="utf-8")


def sha256_file(path: Path) -> str:
    """Return the hex-encoded SHA-256 digest of a file's contents."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


@contextmanager
def _registry_lock():
    """Exclusive file lock protecting registry.json and autoload.json write cycles."""
    _ensure_store()
    lock_path = _plugins_dir() / "registry.lock"
    if sys.platform == "win32":
        import msvcrt

        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)
    else:
        import fcntl

        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def get_registry() -> Dict:
    _ensure_store()
    return json.loads(_registry_file().read_text(encoding="utf-8"))


def _save_registry(registry: Dict):
    _registry_file().write_text(json.dumps(registry, indent=2), encoding="utf-8")


def get_autoload_list() -> List[str]:
    """Return the list of plugin names to enable on startup."""
    _ensure_store()
    f = _autoload_file()
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def set_autoload(name: str, enabled: bool) -> None:
    """Add or remove *name* from the autoload list."""
    with _registry_lock():
        f = _autoload_file()
        try:
            current: List[str] = (
                json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
            )
            if not isinstance(current, list):
                current = []
        except Exception:
            current = []

        if enabled and name not in current:
            current.append(name)
        elif not enabled and name in current:
            current.remove(name)

        f.write_text(json.dumps(current, indent=2), encoding="utf-8")


def register_plugin(manifest: PluginManifest, engine_src: str):
    """Copy engine + metadata into the plugin store and update the registry index."""
    _ensure_store()

    with _registry_lock():
        plugin_dir = _plugins_dir() / manifest.name
        plugin_dir.mkdir(exist_ok=True)

        # Preserve installed_at across updates
        existing_installed_at: str | None = None
        existing_meta = plugin_dir / "metadata.json"
        if existing_meta.exists():
            try:
                existing_installed_at = json.loads(
                    existing_meta.read_text(encoding="utf-8")
                ).get("installed_at")
            except Exception:
                pass

        engine_dest = plugin_dir / "engine.py"
        # write_bytes (not shutil.copy2) so the stored file always gets a fresh
        # mtime, preventing Python's pyc cache from serving stale bytecode when
        # the same plugin is re-registered with content of identical byte-length.
        engine_dest.write_bytes(Path(engine_src).read_bytes())

        checksum = sha256_file(engine_dest)
        now = datetime.now(timezone.utc).isoformat()

        clis_stored: dict = {}
        for cli_name, spec in (manifest.clis or {}).items():
            abs_file, func = spec.rsplit(":", 1)
            cli_dest = plugin_dir / f"cli_{cli_name}.py"
            cli_dest.write_bytes(Path(abs_file).read_bytes())
            clis_stored[cli_name] = f"{cli_dest}:{func}"

        meta_payload = {
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "author": manifest.author,
            "methods": manifest.methods,
            "target": manifest.target,
            "dependencies": manifest.dependencies,
            "engine_path": str(engine_dest),
            "engine_sha256": checksum,
            "license": manifest.license,
            "min_cozy_kit_version": manifest.min_cozy_kit_version,
            "python_requires": manifest.python_requires,
            "tags": manifest.tags,
            "conflict_with": manifest.conflict_with,
            "clis": clis_stored,
            "official": manifest.official,
            "builtin": manifest.builtin,
            "installed_at": existing_installed_at or now,
            "updated_at": now,
        }
        (plugin_dir / "metadata.json").write_text(
            json.dumps(meta_payload, indent=2), encoding="utf-8"
        )

        registry = json.loads(_registry_file().read_text(encoding="utf-8"))
        registry[manifest.name] = {
            "version": manifest.version,
            "path": str(plugin_dir),
            "target": manifest.target,
            "tags": manifest.tags,
            "official": manifest.official,
            "builtin": manifest.builtin,
            "clis": list((manifest.clis or {}).keys()),
        }
        _save_registry(registry)

    _log.info("Registered plugin '%s' v%s.", manifest.name, manifest.version)


def fetch_plugin(name: str) -> Dict:
    """Return the full metadata dict for a registered plugin."""
    registry = get_registry()
    if name not in registry:
        raise PluginNotFoundError(f"Plugin '{name}' is not registered.")

    meta_file = Path(registry[name]["path"]) / "metadata.json"
    return json.loads(meta_file.read_text(encoding="utf-8"))


def unregister_plugin(name: str):
    """Remove a plugin from the store and the registry index."""
    with _registry_lock():
        registry = json.loads(_registry_file().read_text(encoding="utf-8"))
        if name not in registry:
            raise PluginNotFoundError(f"Plugin '{name}' is not registered.")

        plugin_dir = Path(registry[name]["path"])
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)

        del registry[name]
        _save_registry(registry)

    # Outside the lock: autoload cleanup and sys.modules purge
    set_autoload(name, False)
    for prefix in ("_cozy_install_", "_cozy_plugin_", "_cozy_stub_engine_"):
        sys.modules.pop(f"{prefix}{name}", None)

    _log.info("Unregistered plugin '%s'.", name)


def list_plugins() -> Dict:
    """Return the registry index (name → version/path/target)."""
    return get_registry()
