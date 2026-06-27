"""
Edge-case tests for the official + built-in plugin fields.

Covers:
  1. Trusted token resolves to display name, sets official=True + builtin=True
  2. Untrusted author: official and built-in are silently forced to False
  3. Validator warns when untrusted author uses official/built-in: true
  4. Validator errors when built-in limit (10) is already reached
  5. Publisher enforces the 10-plugin limit at registration time
  6. Stored metadata never contains the raw token
"""

import json
import os
import sys
from pathlib import Path

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

TRUSTED_TOKEN = "yOdEV198.author(owner)363"
DISPLAY_NAME = "Youssef Ahmed (owner/author)"

PLUGIN_ROOT = Path(__file__).parent.parent


def _make_metadata(tmp: Path, overrides: dict) -> Path:
    base = {
        "name": "test_plugin",
        "version": "1.0.0",
        "description": "A test plugin.",
        "author": "Random Dev",
        "license": "MIT",
        "methods": ["hello"],
    }
    base.update(overrides)
    p = tmp / "metadata.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


def _make_engine(tmp: Path, extra: str = "") -> Path:
    p = tmp / "engine.py"
    p.write_text(f"def hello(): pass\n{extra}", encoding="utf-8")
    return p


# ── 1. resolve_author ─────────────────────────────────────────────────────────


def test_trusted_token_resolves():
    from cozy_kit._internal._trusted import resolve_author

    name, trusted = resolve_author(TRUSTED_TOKEN)
    assert name == DISPLAY_NAME
    assert trusted is True


def test_untrusted_author_passthrough():
    from cozy_kit._internal._trusted import resolve_author

    name, trusted = resolve_author("Random Dev")
    assert name == "Random Dev"
    assert trusted is False


# ── 2. publisher: untrusted author cannot set official/built-in ───────────────


def test_untrusted_official_forced_false(tmp_path):
    meta = _make_metadata(tmp_path, {"official": True, "author": "Random Dev"})
    engine = _make_engine(tmp_path)

    env = {**os.environ, "COZY_KIT_PLUGINS_DIR": str(tmp_path / "store")}
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import os; os.environ['COZY_KIT_PLUGINS_DIR'] = {str(tmp_path / 'store')!r}; "
            f"from cozy_kit.plugins.core.publisher import plugin; "
            f"m = plugin({str(meta)!r}, {str(engine)!r}); "
            f"print(m.official, m.builtin)",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False"


def test_trusted_author_official_and_builtin(tmp_path):
    meta = _make_metadata(
        tmp_path, {"official": True, "built-in": True, "author": TRUSTED_TOKEN}
    )
    engine = _make_engine(tmp_path)
    store = tmp_path / "store"

    env = {**os.environ, "COZY_KIT_PLUGINS_DIR": str(store)}
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import os; os.environ['COZY_KIT_PLUGINS_DIR'] = {str(store)!r}; "
            f"from cozy_kit.plugins.core.publisher import plugin; "
            f"m = plugin({str(meta)!r}, {str(engine)!r}); "
            f"print(m.official, m.builtin, m.author)",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout.strip()
    assert out == f"True True {DISPLAY_NAME}"


# ── 3. stored metadata never contains the raw token ──────────────────────────


def test_token_not_stored(tmp_path):
    meta = _make_metadata(
        tmp_path, {"official": True, "built-in": True, "author": TRUSTED_TOKEN}
    )
    engine = _make_engine(tmp_path)
    store = tmp_path / "store"

    env = {**os.environ, "COZY_KIT_PLUGINS_DIR": str(store)}
    import subprocess

    subprocess.run(
        [
            sys.executable,
            "-c",
            f"import os; os.environ['COZY_KIT_PLUGINS_DIR'] = {str(store)!r}; "
            f"from cozy_kit.plugins.core.publisher import plugin; "
            f"plugin({str(meta)!r}, {str(engine)!r})",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    # Walk every file in the store — token must never appear
    for f in store.rglob("*"):
        if f.is_file():
            content = f.read_text(encoding="utf-8", errors="replace")
            assert TRUSTED_TOKEN not in content, f"Token found in stored file: {f}"


# ── 4. validator: warns for untrusted official/built-in ──────────────────────


def test_validator_warns_untrusted_official(tmp_path):
    from cozy_kit.plugins.core.validator import validate_plugin

    meta = _make_metadata(tmp_path, {"official": True, "author": "Random Dev"})
    engine = _make_engine(tmp_path)

    result = validate_plugin(str(meta), str(engine))
    assert result.is_valid
    assert any("official" in w and "trusted" in w for w in result.warnings)


def test_validator_warns_untrusted_builtin(tmp_path):
    from cozy_kit.plugins.core.validator import validate_plugin

    meta = _make_metadata(tmp_path, {"built-in": True, "author": "Random Dev"})
    engine = _make_engine(tmp_path)

    result = validate_plugin(str(meta), str(engine))
    assert result.is_valid
    assert any("built-in" in w and "trusted" in w for w in result.warnings)


def test_validator_no_warning_for_trusted(tmp_path):
    from cozy_kit.plugins.core.validator import validate_plugin

    meta = _make_metadata(
        tmp_path, {"official": True, "built-in": True, "author": TRUSTED_TOKEN}
    )
    engine = _make_engine(tmp_path)

    result = validate_plugin(str(meta), str(engine))
    assert result.is_valid
    assert not any("not a trusted" in w for w in result.warnings)


# ── 5. validator: errors when built-in limit is reached ──────────────────────


def test_validator_builtin_limit(tmp_path, monkeypatch):
    """Validator should error when 10 built-in plugins are already registered."""
    # The validator imports get_registry/fetch_plugin lazily from registry,
    # so we patch the registry module's own names.
    import cozy_kit.plugins.core.registry as _reg

    fake_registry = {f"plugin_{i}": {} for i in range(10)}
    monkeypatch.setattr(_reg, "get_registry", lambda: fake_registry)
    monkeypatch.setattr(_reg, "fetch_plugin", lambda name: {"builtin": True})

    meta = _make_metadata(tmp_path, {"built-in": True, "author": TRUSTED_TOKEN})
    engine = _make_engine(tmp_path)

    from cozy_kit.plugins.core.validator import validate_plugin

    result = validate_plugin(str(meta), str(engine))
    assert not result.is_valid
    assert any("limit" in e for e in result.errors)


# ── 6. publisher: errors when built-in limit is reached ──────────────────────


def test_publisher_builtin_limit(tmp_path, monkeypatch):
    """Publisher should raise InvalidMetadataError when 10 builtins exist."""
    fake_registry = {f"plugin_{i}": {} for i in range(10)}
    monkeypatch.setattr(
        "cozy_kit.plugins.core.publisher.get_registry",
        lambda: fake_registry,
    )
    monkeypatch.setattr(
        "cozy_kit.plugins.core.publisher.fetch_plugin",
        lambda name: {"builtin": True},
    )

    meta = _make_metadata(tmp_path, {"built-in": True, "author": TRUSTED_TOKEN})
    engine = _make_engine(tmp_path)

    os.environ["COZY_KIT_PLUGINS_DIR"] = str(tmp_path / "store")
    try:
        from cozy_kit._internal.errors.plugin_errors import InvalidMetadataError
        from cozy_kit.plugins.core.publisher import plugin

        with pytest.raises(InvalidMetadataError, match="limit"):
            plugin(str(meta), str(engine))
    finally:
        os.environ.pop("COZY_KIT_PLUGINS_DIR", None)
