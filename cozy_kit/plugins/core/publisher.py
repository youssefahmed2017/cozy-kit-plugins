import json
import logging
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from cozy_kit._internal.models.manifest import PluginManifest
from cozy_kit._internal.models.context import PluginContext
from cozy_kit._internal.errors.plugin_errors import (
    InvalidMetadataError,
    EngineNotFoundError,
    PluginAlreadyExistsError,
    PluginLifecycleError,
)
from cozy_kit.plugins.core.registry import (
    register_plugin,
    get_registry,
    fetch_plugin,
    unregister_plugin,
)
from cozy_kit._internal.helpers.import_helpers import load_module_from_path
from cozy_kit._internal.helpers.plugin_lifecycle import call_hook
from cozy_kit._internal.helpers.dep_helpers import validate_dep_spec
from cozy_kit._internal._trusted import resolve_author

_log = logging.getLogger("cozy_kit.plugins.publisher")

_REQUIRED_FIELDS = {"name", "version", "description", "author", "methods"}


def plugin(metadata: str, engine: str, overwrite: bool = False) -> PluginManifest:
    """
    Register a plugin with the cozy-kit plugin system.

    Args:
        metadata: Path to the plugin's JSON metadata file (.json extension optional).
        engine:   Path to the plugin's Python engine file (.py extension optional).
        overwrite: Replace an already-registered plugin with the same name.
                   Triggers on_update() instead of on_install() when True.

    Returns:
        The validated PluginManifest that was stored.
    """
    meta_path = Path(metadata)
    if not meta_path.suffix:
        meta_path = meta_path.with_suffix(".json")
    if not meta_path.exists():
        raise InvalidMetadataError(f"Metadata file not found: {meta_path}")

    try:
        meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidMetadataError(
            f"Metadata file contains invalid JSON: {exc}"
        ) from exc

    missing = _REQUIRED_FIELDS - set(meta_data.keys())
    if missing:
        raise InvalidMetadataError(f"Metadata is missing required fields: {missing}")

    if not isinstance(meta_data["methods"], list) or not meta_data["methods"]:
        raise InvalidMetadataError(
            "'methods' must be a non-empty list of method names."
        )

    if not isinstance(meta_data["name"], str) or not meta_data["name"].strip():
        raise InvalidMetadataError("'name' must be a non-empty string.")

    raw_author = meta_data.get("author", "")
    display_author, is_trusted = resolve_author(raw_author)
    official = bool(meta_data.get("official", False)) and is_trusted

    deps = meta_data.get("dependencies", [])
    if not isinstance(deps, list):
        raise InvalidMetadataError("'dependencies' must be a list of strings.")
    for dep in deps:
        if not isinstance(dep, str) or not dep.strip():
            raise InvalidMetadataError(
                f"Each dependency must be a non-empty string, got: {dep!r}"
            )
        validate_dep_spec(dep)

    tags = meta_data.get("tags", [])
    if not isinstance(tags, list):
        raise InvalidMetadataError("'tags' must be a list of strings.")
    for t in tags:
        if not isinstance(t, str) or not t.strip():
            raise InvalidMetadataError(
                f"Each entry in 'tags' must be a non-empty string, got: {t!r}"
            )

    conflict_with = meta_data.get("conflict_with", [])
    if not isinstance(conflict_with, list):
        raise InvalidMetadataError(
            "'conflict_with' must be a list of plugin name strings."
        )
    for c in conflict_with:
        if not isinstance(c, str) or not c.strip():
            raise InvalidMetadataError(
                f"Each entry in 'conflict_with' must be a non-empty string, got: {c!r}"
            )

    py_req = meta_data.get("python_requires")
    if py_req is not None:
        if not isinstance(py_req, str):
            raise InvalidMetadataError("'python_requires' must be a string.")
        try:
            SpecifierSet(py_req)
        except InvalidSpecifier as exc:
            raise InvalidMetadataError(
                f"'python_requires' {py_req!r} is not a valid PEP 440 specifier: {exc}"
            ) from exc

    min_ck = meta_data.get("min_cozy_kit_version")
    if min_ck is not None:
        if not isinstance(min_ck, str):
            raise InvalidMetadataError("'min_cozy_kit_version' must be a string.")
        try:
            Version(min_ck)
        except InvalidVersion as exc:
            raise InvalidMetadataError(
                f"'min_cozy_kit_version' {min_ck!r} is not a valid version string: {exc}"
            ) from exc

    clis_raw = meta_data.get("CLIs", {})
    if not isinstance(clis_raw, dict):
        raise InvalidMetadataError("'CLIs' must be a dict mapping command names to 'file.py:func' strings.")
    for cli_name, spec in clis_raw.items():
        if not isinstance(cli_name, str) or not cli_name.strip():
            raise InvalidMetadataError(f"CLI command name must be a non-empty string, got: {cli_name!r}")
        if not isinstance(spec, str) or ":" not in spec:
            raise InvalidMetadataError(
                f"CLI spec for '{cli_name}' must be 'file.py:function', got: {spec!r}"
            )

    engine_path = Path(engine)
    if not engine_path.suffix:
        engine_path = engine_path.with_suffix(".py")
    if not engine_path.exists():
        raise EngineNotFoundError(f"Engine file not found: {engine_path}")

    engine_dir = engine_path.parent
    resolved_clis: dict = {}
    for cli_name, spec in clis_raw.items():
        file_part, _, func_part = spec.partition(":")
        if not func_part.strip():
            raise InvalidMetadataError(
                f"CLI spec for '{cli_name}' is missing a function name: {spec!r}"
            )
        cli_file = engine_dir / file_part
        if not cli_file.exists():
            raise InvalidMetadataError(
                f"CLI file for '{cli_name}' not found: {cli_file}"
            )
        resolved_clis[cli_name] = f"{cli_file}:{func_part.strip()}"

    name = meta_data["name"].strip()
    registry = get_registry()
    is_update = name in registry and overwrite

    if name in registry and not overwrite:
        raise PluginAlreadyExistsError(
            f"Plugin '{name}' is already registered. Pass overwrite=True to replace it."
        )

    old_version: str = fetch_plugin(name).get("version", "") if is_update else ""

    manifest = PluginManifest(
        name=name,
        version=meta_data["version"],
        description=meta_data["description"],
        author=display_author,
        methods=meta_data["methods"],
        target=meta_data.get("target"),
        dependencies=deps,
        license=meta_data.get("license"),
        min_cozy_kit_version=meta_data.get("min_cozy_kit_version"),
        python_requires=meta_data.get("python_requires"),
        tags=tags,
        conflict_with=conflict_with,
        clis=resolved_clis,
        official=official,
    )

    register_plugin(manifest, str(engine_path))

    module = load_module_from_path(str(engine_path), f"_cozy_install_{name}")
    ctx = PluginContext(
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        author=manifest.author,
        methods=manifest.methods,
        target=manifest.target,
        dependencies=manifest.dependencies,
    )

    if is_update:
        _log.info("Updating plugin '%s': %s → %s.", name, old_version, manifest.version)
        try:
            call_hook(module, "on_update", ctx, name, extra_args=(old_version,))
        except PluginLifecycleError:
            raise
    else:
        try:
            call_hook(module, "on_install", ctx, name)
        except PluginLifecycleError:
            try:
                unregister_plugin(name)
            except Exception:
                pass
            raise

    return manifest
