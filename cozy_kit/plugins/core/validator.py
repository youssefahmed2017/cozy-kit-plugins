"""Dry-run plugin validation — checks metadata and engine without registering."""

import ast
import json
from pathlib import Path
from typing import List, NamedTuple

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from cozy_kit._internal.errors.plugin_errors import InvalidMetadataError
from cozy_kit._internal.helpers.dep_helpers import validate_dep_spec

_REQUIRED_FIELDS = {"name", "version", "description", "author", "methods"}


class ValidationResult(NamedTuple):
    errors: List[str]
    warnings: List[str]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def validate_plugin(metadata: str, engine: str) -> ValidationResult:
    """
    Validate a plugin without registering it.

    Checks metadata structure, field types, version specifiers, engine syntax,
    and that the engine defines all methods declared in metadata.

    Returns a ValidationResult with separate errors and warnings lists.
    A plugin is valid when errors is empty; warnings are advisory only.
    """
    errors: List[str] = []
    warnings: List[str] = []

    meta_path = Path(metadata)
    if not meta_path.suffix:
        meta_path = meta_path.with_suffix(".json")

    if not meta_path.exists():
        return ValidationResult([f"Metadata file not found: {meta_path}"], warnings)

    try:
        meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ValidationResult([f"Invalid JSON: {exc}"], warnings)

    if not isinstance(meta_data, dict):
        return ValidationResult(["Metadata must be a JSON object."], warnings)

    missing = _REQUIRED_FIELDS - set(meta_data.keys())
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")

    name = meta_data.get("name", "")
    if not isinstance(name, str) or not name.strip():
        errors.append("'name' must be a non-empty string.")

    version_str = meta_data.get("version", "")
    if not isinstance(version_str, str) or not version_str.strip():
        errors.append("'version' must be a non-empty string.")
    else:
        try:
            Version(version_str)
        except InvalidVersion:
            warnings.append(
                f"'version' {version_str!r} is not a valid PEP 440 version "
                "(e.g. '1.0.0'). Dependency resolution may be unreliable."
            )

    desc = meta_data.get("description", "")
    if not isinstance(desc, str) or not desc.strip():
        errors.append("'description' must be a non-empty string.")

    author = meta_data.get("author", "")
    if not isinstance(author, str) or not author.strip():
        errors.append("'author' must be a non-empty string.")

    methods = meta_data.get("methods")
    if not isinstance(methods, list) or not methods:
        errors.append("'methods' must be a non-empty list.")
        methods = []
    elif any(not isinstance(m, str) or not m.strip() for m in methods):
        errors.append("Each entry in 'methods' must be a non-empty string.")

    deps = meta_data.get("dependencies", [])
    if not isinstance(deps, list):
        errors.append("'dependencies' must be a list.")
    else:
        for dep in deps:
            if not isinstance(dep, str) or not dep.strip():
                errors.append(f"Invalid dependency entry: {dep!r}")
            else:
                try:
                    validate_dep_spec(dep)
                except InvalidMetadataError as exc:
                    errors.append(str(exc))

    py_req = meta_data.get("python_requires")
    if py_req is not None:
        if not isinstance(py_req, str):
            errors.append("'python_requires' must be a string.")
        else:
            try:
                SpecifierSet(py_req)
            except InvalidSpecifier:
                errors.append(
                    f"'python_requires' {py_req!r} is not a valid PEP 440 specifier."
                )

    min_ck = meta_data.get("min_cozy_kit_version")
    if min_ck is not None:
        if not isinstance(min_ck, str):
            errors.append("'min_cozy_kit_version' must be a string.")
        else:
            try:
                Version(min_ck)
            except InvalidVersion:
                errors.append(
                    f"'min_cozy_kit_version' {min_ck!r} is not a valid version string."
                )

    tags = meta_data.get("tags", [])
    if not isinstance(tags, list):
        errors.append("'tags' must be a list of strings.")
    elif any(not isinstance(t, str) or not t.strip() for t in tags):
        errors.append("Each entry in 'tags' must be a non-empty string.")

    conflicts = meta_data.get("conflict_with", [])
    if not isinstance(conflicts, list):
        errors.append("'conflict_with' must be a list of plugin name strings.")
    elif any(not isinstance(c, str) or not c.strip() for c in conflicts):
        errors.append("Each entry in 'conflict_with' must be a non-empty string.")

    clis = meta_data.get("CLIs", {})
    if not isinstance(clis, dict):
        errors.append("'CLIs' must be a dict mapping command names to 'file.py:func' strings.")
    else:
        for cli_name, spec in clis.items():
            if not isinstance(cli_name, str) or not cli_name.strip():
                errors.append(f"CLI command name must be a non-empty string, got: {cli_name!r}")
                continue
            if not isinstance(spec, str) or ":" not in spec:
                errors.append(f"CLI spec for '{cli_name}' must be 'file.py:function', got: {spec!r}")
                continue
            file_part, _, func_part = spec.partition(":")
            if not func_part.strip():
                errors.append(f"CLI spec for '{cli_name}' is missing a function name: {spec!r}")

    if meta_data.get("official") is not None:
        if not isinstance(meta_data["official"], bool):
            errors.append("'official' must be a boolean.")
        elif meta_data["official"]:
            from cozy_kit._internal._trusted import resolve_author
            _, is_trusted = resolve_author(meta_data.get("author", ""))
            if not is_trusted:
                warnings.append(
                    "'official: true' is set but the author is not a trusted maintainer — "
                    "this field will be ignored at registration time."
                )

    if "license" not in meta_data:
        warnings.append(
            "No 'license' field. Consider adding one (e.g. 'MIT', 'Apache-2.0')."
        )

    eng_path = Path(engine)
    if not eng_path.suffix:
        eng_path = eng_path.with_suffix(".py")

    if not eng_path.exists():
        errors.append(f"Engine file not found: {eng_path}")
        return ValidationResult(errors, warnings)

    source = eng_path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=str(eng_path))
    except SyntaxError as exc:
        errors.append(f"Engine syntax error: {exc}")
        return ValidationResult(errors, warnings)

    defined_fns = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for method in methods:
        if isinstance(method, str) and method.strip() and method not in defined_fns:
            errors.append(f"Engine does not define '{method}'.")

    return ValidationResult(errors, warnings)
