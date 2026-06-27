import importlib
import logging
import os
import stat
import sys as _sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from cozy_kit.plugins.core.registry import (
    fetch_plugin,
    get_autoload_list,
    get_registry,
    set_autoload,
    unregister_plugin,
    sha256_file,
)
from cozy_kit._internal.errors.plugin_errors import (
    CircularDependencyError,
    InvalidEngineError,
    InvalidMetadataError,
    MethodCollisionError,
    MissingDependencyError,
    PluginCLIError,
    PluginCompatibilityError,
    PluginConflictError,
    PluginIntegrityError,
    PluginNotFoundError,
    TargetClassNotFoundError,
)
from cozy_kit._internal.models.context import PluginContext
from cozy_kit._internal.helpers.dep_helpers import check_dep_version, parse_dep
from cozy_kit._internal.helpers.import_helpers import load_module_from_path
from cozy_kit._internal.helpers.plugin_lifecycle import call_hook

_log = logging.getLogger("cozy_kit.plugins.installer")

_COZY_KIT_TARGETS: Dict[str, tuple] = {
    "Greeting": ("cozy_kit.greeting", "Greeting"),
    "Timer": ("cozy_kit.timer", "Timer"),
    "TextEditor": ("cozy_kit.text_studio", "TextEditor"),
    "TextCustomizations": ("cozy_kit.text_studio", "TextCustomizations"),
    "CozyUI": ("cozy_kit.ui", "CozyUI"),
    "SMTPMailer": ("cozy_kit.mailer", "SMTPMailer"),
}

_custom_targets: Dict[str, type] = {}
_standalone_plugins: Dict[str, Dict[str, Callable]] = {}
_enabled_plugins: Set[str] = set()
_method_ownership: Dict[str, Dict[str, str]] = {}
_cli_registry: Dict[str, Dict[str, str]] = {}  # {cli_name: {file, func, plugin}}


def _scripts_dir() -> Path:
    """Return the Python env's Scripts/bin directory (same place cozy-plugins lives)."""
    import sysconfig
    return Path(sysconfig.get_path("scripts"))


def _write_cli_script(cli_name: str, cli_file: str, func: str) -> None:
    """Write a platform-appropriate wrapper script for *cli_name*."""
    scripts = _scripts_dir()
    wrapper = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('_cozy_cli_{cli_name}', {cli_file!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        f"sys.exit(getattr(m, {func!r})() or 0)\n"
    )
    if _sys.platform == "win32":
        script_py = scripts / f"{cli_name}-script.py"
        script_py.write_text(wrapper, encoding="utf-8")
        cmd = scripts / f"{cli_name}.cmd"
        cmd.write_text(
            f'@"%~dp0python.exe" "%~dp0{cli_name}-script.py" %*\r\n',
            encoding="utf-8",
        )
    else:
        script = scripts / cli_name
        script.write_text(f"#!/usr/bin/env python\n{wrapper}", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _remove_cli_script(cli_name: str) -> None:
    """Delete the wrapper script(s) for *cli_name* if they exist."""
    scripts = _scripts_dir()
    if _sys.platform == "win32":
        for name in (f"{cli_name}-script.py", f"{cli_name}.cmd"):
            p = scripts / name
            if p.exists():
                p.unlink()
    else:
        p = scripts / cli_name
        if p.exists():
            p.unlink()


def register_target(name: str, cls: type) -> None:
    """Register a custom class as a valid plugin target (useful for testing)."""
    _custom_targets[name] = cls


def _resolve_target(target_name: str) -> type:
    if target_name in _custom_targets:
        return _custom_targets[target_name]
    if target_name not in _COZY_KIT_TARGETS:
        raise TargetClassNotFoundError(
            f"Unknown target class '{target_name}'. "
            f"Built-in targets: {list(_COZY_KIT_TARGETS)}. "
            "Use register_target() to add a custom one."
        )
    module_path, class_name = _COZY_KIT_TARGETS[target_name]
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    except (ImportError, AttributeError) as exc:
        raise TargetClassNotFoundError(
            f"Could not import '{target_name}' from '{module_path}': {exc}"
        ) from exc


def _make_context(plugin_data: dict) -> PluginContext:
    return PluginContext(
        name=plugin_data["name"],
        version=plugin_data["version"],
        description=plugin_data["description"],
        author=plugin_data["author"],
        methods=plugin_data["methods"],
        target=plugin_data.get("target"),
        dependencies=plugin_data.get("dependencies", []),
    )


def _check_conflicts(plugin_name: str, plugin_data: dict) -> None:
    """Raise PluginConflictError if any conflicting plugin is already enabled."""
    for conflicting in plugin_data.get("conflict_with", []):
        if conflicting in _enabled_plugins:
            raise PluginConflictError(
                f"Plugin '{plugin_name}' conflicts with '{conflicting}', "
                f"which is currently enabled. Disable '{conflicting}' first."
            )
    for enabled_name in list(_enabled_plugins):
        try:
            enabled_data = fetch_plugin(enabled_name)
        except Exception:
            continue
        if plugin_name in enabled_data.get("conflict_with", []):
            raise PluginConflictError(
                f"Plugin '{enabled_name}' (currently enabled) conflicts with "
                f"'{plugin_name}'."
            )


def _check_compatibility(plugin_name: str, plugin_data: dict) -> None:
    """Raise PluginCompatibilityError if runtime env doesn't satisfy plugin requirements."""
    py_req = plugin_data.get("python_requires")
    if py_req:
        try:
            spec = SpecifierSet(py_req)
            current = Version(
                f"{_sys.version_info.major}.{_sys.version_info.minor}"
                f".{_sys.version_info.micro}"
            )
            if current not in spec:
                raise PluginCompatibilityError(
                    f"Plugin '{plugin_name}' requires Python {py_req}, "
                    f"but the current Python is {current}."
                )
        except PluginCompatibilityError:
            raise
        except Exception as exc:
            _log.debug("Could not check python_requires for '%s': %s", plugin_name, exc)

    min_ck = plugin_data.get("min_cozy_kit_version")
    if min_ck:
        try:
            import cozy_kit as _cozy_kit

            if Version(_cozy_kit.__version__) < Version(min_ck):
                raise PluginCompatibilityError(
                    f"Plugin '{plugin_name}' requires cozy_kit>={min_ck}, "
                    f"but {_cozy_kit.__version__} is installed."
                )
        except ImportError:
            _log.warning(
                "Cannot verify min_cozy_kit_version for '%s': cozy_kit is not installed.",
                plugin_name,
            )
        except PluginCompatibilityError:
            raise
        except InvalidVersion:
            _log.debug(
                "Could not parse version strings while checking min_cozy_kit_version "
                "for '%s'.",
                plugin_name,
            )


def _verify_integrity(plugin_name: str, plugin_data: dict) -> None:
    """Raise PluginIntegrityError if the stored engine no longer matches its registered SHA-256."""
    expected = plugin_data.get("engine_sha256")
    if not expected:
        return
    engine_path = Path(plugin_data["engine_path"])
    actual = sha256_file(engine_path)
    if actual != expected:
        raise PluginIntegrityError(
            f"Engine for '{plugin_name}' failed integrity check "
            f"(expected {expected[:16]}…, got {actual[:16]}…). "
            "The file may have been tampered with. Re-register the plugin to update its checksum."
        )


def _rollback_plugin(plugin_name: str) -> None:
    """Undo a plugin's patches without calling any lifecycle hooks (used on install failure)."""
    try:
        plugin_data = fetch_plugin(plugin_name)
    except Exception:
        return
    target_name = plugin_data.get("target")
    methods = plugin_data.get("methods", [])
    if target_name:
        try:
            target_cls = _resolve_target(target_name)
        except Exception:
            return
        ownership = _method_ownership.get(target_name, {})
        for method_name in methods:
            if ownership.get(method_name) == plugin_name:
                if hasattr(target_cls, method_name):
                    delattr(target_cls, method_name)
                ownership.pop(method_name, None)
    _standalone_plugins.pop(plugin_name, None)
    for cli_name in [k for k, v in _cli_registry.items() if v["plugin"] == plugin_name]:
        _remove_cli_script(cli_name)
        del _cli_registry[cli_name]
    _enabled_plugins.discard(plugin_name)


def _collect_all_deps(names: List[str], registry: Dict) -> List[str]:
    visited: Set[str] = set()
    result: List[str] = []

    def _visit(name: str, is_root: bool = False) -> None:
        if name in visited:
            return
        if name not in registry:
            if is_root:
                raise PluginNotFoundError(f"Plugin '{name}' is not registered.")
            raise MissingDependencyError(f"Plugin '{name}' is not registered.")
        visited.add(name)
        for dep_str in fetch_plugin(name).get("dependencies", []):
            dep_name, _ = parse_dep(dep_str)
            if dep_name not in registry:
                raise MissingDependencyError(
                    f"Plugin '{name}' requires '{dep_str}' which is not registered."
                )
            dep_installed_version = registry[dep_name].get("version", "0.0.0")
            check_dep_version(dep_str, dep_installed_version)
            _visit(dep_name)
        result.append(name)

    for n in names:
        _visit(n, is_root=True)
    return result


def _topological_sort(names: List[str]) -> List[str]:
    registry = get_registry()
    all_names = _collect_all_deps(names, registry)

    graph: Dict[str, List[str]] = {n: [] for n in all_names}
    in_degree: Dict[str, int] = {n: 0 for n in all_names}

    for name in all_names:
        for dep_str in fetch_plugin(name).get("dependencies", []):
            dep_name, _ = parse_dep(dep_str)
            if dep_name in graph:
                graph[dep_name].append(name)
                in_degree[name] += 1

    queue = [n for n in all_names if in_degree[n] == 0]
    ordered: List[str] = []
    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(ordered) != len(all_names):
        cycle = [n for n in all_names if in_degree[n] > 0]
        raise CircularDependencyError(f"Circular dependency detected among: {cycle}")

    return ordered


def add_plugin(name: str) -> None:
    """
    Install a plugin (and all its dependencies, in dependency-first order).

    - Dependency version specifiers are enforced.
    - The engine file's SHA-256 is verified before execution.
    - Method collisions raise MethodCollisionError.
    - on_enable() is called after patching.
    - Any failure triggers a full rollback of patches applied this call.
    - On success, the plugin is added to the autoload list for session persistence.
    """
    load_order = _topological_sort([name])
    patched_this_call: List[str] = []

    try:
        for plugin_name in load_order:
            if plugin_name in _enabled_plugins:
                continue

            plugin_data = fetch_plugin(plugin_name)
            engine_path: str = plugin_data["engine_path"]
            target_name: Optional[str] = plugin_data.get("target")
            methods: List[str] = plugin_data["methods"]

            _verify_integrity(plugin_name, plugin_data)
            _check_compatibility(plugin_name, plugin_data)
            _check_conflicts(plugin_name, plugin_data)

            module = load_module_from_path(engine_path, f"_cozy_plugin_{plugin_name}")
            ctx = _make_context(plugin_data)

            if target_name:
                target_cls = _resolve_target(target_name)
                ownership = _method_ownership.setdefault(target_name, {})

                for method_name in methods:
                    existing_owner = ownership.get(method_name)
                    if existing_owner is not None and existing_owner != plugin_name:
                        raise MethodCollisionError(
                            f"Plugin '{plugin_name}' cannot add '{method_name}' to "
                            f"{target_name}: already owned by '{existing_owner}'."
                        )

                for method_name in methods:
                    fn = getattr(module, method_name, None)
                    if fn is None:
                        raise InvalidEngineError(
                            f"Engine for plugin '{plugin_name}' does not define '{method_name}'."
                        )
                    setattr(target_cls, method_name, fn)
                    ownership[method_name] = plugin_name
                    _log.debug(
                        "Patched %s.%s ← plugin '%s'.",
                        target_name,
                        method_name,
                        plugin_name,
                    )

            else:
                exposed: Dict[str, Callable] = {}
                for fn_name in methods:
                    fn = getattr(module, fn_name, None)
                    if fn is None:
                        raise InvalidEngineError(
                            f"Engine for plugin '{plugin_name}' does not define '{fn_name}'."
                        )
                    exposed[fn_name] = fn
                _standalone_plugins[plugin_name] = exposed

            patched_this_call.append(plugin_name)

            for cli_name, spec in plugin_data.get("clis", {}).items():
                abs_file, func = spec.rsplit(":", 1)
                _cli_registry[cli_name] = {
                    "file": abs_file,
                    "func": func,
                    "plugin": plugin_name,
                }
                _write_cli_script(cli_name, abs_file, func)
                _log.debug("Registered CLI '%s' ← plugin '%s'.", cli_name, plugin_name)

            call_hook(module, "on_enable", ctx, plugin_name)
            _enabled_plugins.add(plugin_name)
            _log.info("Enabled plugin '%s'.", plugin_name)

    except Exception:
        for pname in reversed(patched_this_call):
            _rollback_plugin(pname)
        raise

    set_autoload(name, True)


def disable_plugin(name: str) -> None:
    """
    Remove a plugin's methods from its target class and call on_disable.
    The plugin stays registered; call remove_plugin() to fully uninstall.

    Works correctly in fresh processes: if the plugin is on the autoload list
    but not yet loaded into memory, on_disable is still fired and CLI scripts
    are removed from disk.
    """
    in_memory = name in _enabled_plugins
    in_autoload = name in get_autoload_list()

    if not in_memory and not in_autoload:
        return

    plugin_data = fetch_plugin(name)
    engine_path: str = plugin_data["engine_path"]
    target_name: Optional[str] = plugin_data.get("target")
    methods: List[str] = plugin_data["methods"]

    module = load_module_from_path(engine_path, f"_cozy_plugin_{name}")
    ctx = _make_context(plugin_data)

    call_hook(module, "on_disable", ctx, name)

    if in_memory:
        if target_name:
            target_cls = _resolve_target(target_name)
            ownership = _method_ownership.get(target_name, {})
            for method_name in methods:
                if ownership.get(method_name) == name:
                    if hasattr(target_cls, method_name):
                        delattr(target_cls, method_name)
                    ownership.pop(method_name, None)
        _standalone_plugins.pop(name, None)
        for cli_name in [k for k, v in _cli_registry.items() if v["plugin"] == name]:
            _remove_cli_script(cli_name)
            del _cli_registry[cli_name]
        _enabled_plugins.discard(name)
    else:
        # Plugin not loaded in this process — remove CLI scripts directly from disk.
        for cli_name in plugin_data.get("clis", {}):
            _remove_cli_script(cli_name)

    set_autoload(name, False)
    _log.info("Disabled plugin '%s'.", name)


def remove_plugin(name: str) -> None:
    """Fully uninstall a plugin: disable it, call on_uninstall, remove from registry."""
    plugin_data = fetch_plugin(name)
    engine_path: str = plugin_data["engine_path"]

    module = load_module_from_path(engine_path, f"_cozy_plugin_{name}")
    ctx = _make_context(plugin_data)

    # disable_plugin handles both in-memory and autoload-only cases.
    if name in _enabled_plugins or name in get_autoload_list():
        disable_plugin(name)

    call_hook(module, "on_uninstall", ctx, name)
    unregister_plugin(name)
    _log.info("Removed plugin '%s'.", name)


def get_cli_entry(cli_name: str) -> Dict[str, str]:
    """Return the registered CLI entry for *cli_name* or raise PluginCLIError."""
    if cli_name not in _cli_registry:
        available = sorted(_cli_registry)
        raise PluginCLIError(
            f"No CLI named '{cli_name}' is currently registered."
            + (f" Available: {available}" if available else "")
        )
    return _cli_registry[cli_name]


def list_clis() -> Dict[str, Dict[str, str]]:
    """Return a snapshot of all currently registered CLIs."""
    return dict(_cli_registry)


def get_plugin_functions(name: str) -> Dict[str, Callable]:
    """Return the callable dict for an installed standalone plugin."""
    if name not in _standalone_plugins:
        raise PluginNotFoundError(
            f"Standalone plugin '{name}' is not installed in this session."
        )
    return _standalone_plugins[name]


def upgrade_plugin(name: str, metadata: str, engine: str):
    """
    Upgrade a registered plugin to a new version, refreshing its runtime state.

    If the plugin is currently enabled this atomically disables it (calling
    on_disable on the OLD engine), registers the new engine (calling on_update),
    then re-enables it (calling on_enable on the NEW engine).
    """
    import json as _json
    from pathlib import Path as _Path
    from cozy_kit.plugins.core.publisher import (
        plugin as _plugin,
    )  # lazy to avoid circular

    registry = get_registry()
    if name not in registry:
        raise PluginNotFoundError(
            f"Plugin '{name}' is not registered. "
            "Use plugin() for first-time installation."
        )

    meta_path = _Path(metadata)
    if not meta_path.suffix:
        meta_path = meta_path.with_suffix(".json")
    try:
        meta_name = _json.loads(meta_path.read_text(encoding="utf-8")).get("name", "")
    except Exception:
        meta_name = ""
    if meta_name != name:
        raise InvalidMetadataError(
            f"upgrade_plugin: metadata 'name' is {meta_name!r}, expected {name!r}."
        )

    was_enabled = name in _enabled_plugins
    was_in_autoload = name in get_autoload_list()

    if was_enabled:
        disable_plugin(name)

    manifest = _plugin(metadata=metadata, engine=engine, overwrite=True)

    # Re-enable if active in this process OR on the autoload list (covers fresh
    # CLI processes where _enabled_plugins is empty but the plugin should be active).
    if was_enabled or was_in_autoload:
        add_plugin(name)

    _log.info("Upgraded plugin '%s' to v%s.", name, manifest.version)
    return manifest


def status() -> Dict:
    """Return a snapshot of the current runtime plugin state."""
    return {
        "enabled": sorted(_enabled_plugins),
        "standalone": {
            name: sorted(fns.keys()) for name, fns in _standalone_plugins.items()
        },
        "method_ownership": {
            target: dict(ownership)
            for target, ownership in _method_ownership.items()
            if ownership
        },
    }


def autoload_plugins() -> Dict[str, Optional[Exception]]:
    """
    Re-enable all plugins that were active in a previous session.

    Reads the autoload list from the plugin store and calls add_plugin() for each
    entry that is not already enabled. Failures are caught and logged rather than
    raised, so a single broken plugin does not prevent the others from loading.
    """
    from cozy_kit.plugins.core._builtins import ensure_builtins_installed

    ensure_builtins_installed(silent=True)

    registry = get_registry()
    results: Dict[str, Optional[Exception]] = {}

    for name in get_autoload_list():
        if name in _enabled_plugins:
            results[name] = None
            continue
        if name not in registry:
            exc = PluginNotFoundError(f"Plugin '{name}' is no longer registered.")
            _log.warning("Autoload skipped '%s': %s", name, exc)
            results[name] = exc
            continue
        try:
            add_plugin(name)
            _log.debug("Autoloaded plugin '%s'.", name)
            results[name] = None
        except Exception as exc:
            _log.warning("Autoload failed for '%s': %s", name, exc)
            results[name] = exc

    return results
