"""Dependency string parsing and version-specifier checking."""

import re
from typing import Tuple

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from cozy_kit._internal.errors.plugin_errors import (
    InvalidMetadataError,
    MissingDependencyError,
)

_DEP_RE = re.compile(r"^([A-Za-z0-9_\-\.]+)(.*)")


def parse_dep(dep_str: str) -> Tuple[str, str]:
    """Split 'plugin_name>=1.0,<2.0' into ('plugin_name', '>=1.0,<2.0')."""
    m = _DEP_RE.match(dep_str.strip())
    if not m:
        raise InvalidMetadataError(f"Invalid dependency string: {dep_str!r}")
    return m.group(1), m.group(2).strip()


def validate_dep_spec(dep_str: str) -> None:
    """Raise InvalidMetadataError if dep_str contains a malformed version specifier."""
    _, spec_str = parse_dep(dep_str)
    if spec_str:
        try:
            SpecifierSet(spec_str)
        except InvalidSpecifier:
            raise InvalidMetadataError(
                f"Invalid version specifier in dependency '{dep_str}': {spec_str!r}"
            )


def check_dep_version(dep_str: str, installed_version: str) -> None:
    """
    Raise MissingDependencyError if installed_version does not satisfy dep_str's specifier.
    Non-PEP-440 installed versions are silently accepted (no check performed).
    """
    name, spec_str = parse_dep(dep_str)
    if not spec_str:
        return
    try:
        specifier = SpecifierSet(spec_str)
        version = Version(installed_version)
        if version not in specifier:
            raise MissingDependencyError(
                f"Dependency '{name}' version {installed_version!r} "
                f"does not satisfy required '{dep_str}'."
            )
    except InvalidVersion:
        pass  # non-PEP-440 version string — skip the check
