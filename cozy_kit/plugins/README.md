# cozy-kit Plugin System

Extend [cozy-kit](https://pypi.org/project/cozy-kit/) by adding new methods to its built-in classes — or shipping standalone utility functions — without modifying the library itself.

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Quick Start](#quick-start)
3. [Creating a Plugin](#creating-a-plugin)
   - [The Metadata File](#the-metadata-file)
   - [All Metadata Fields](#all-metadata-fields)
   - [The Engine File](#the-engine-file)
   - [Lifecycle Hooks](#lifecycle-hooks)
   - [Target Classes](#target-classes)
   - [Standalone Plugins](#standalone-plugins)
4. [Testing Your Plugin Locally](#testing-your-plugin-locally)
5. [Publishing to PyPI](#publishing-to-pypi)
   - [Package Structure](#package-structure)
   - [Naming Convention](#naming-convention)
   - [pyproject.toml for Plugin Packages](#pyprojecttoml-for-plugin-packages)
   - [Making Your Plugin Discoverable](#making-your-plugin-discoverable)
6. [Marketplace](#marketplace)
   - [Browsing the Marketplace](#browsing-the-marketplace)
   - [Installing from the Marketplace](#installing-from-the-marketplace)
   - [Upgrading Plugins](#upgrading-plugins)
   - [Getting Listed in the Marketplace](#getting-listed-in-the-marketplace)
7. [CLI Reference](#cli-reference)
8. [Python API Reference](#python-api-reference)

---

## How It Works

A plugin is two files:

| File             | Purpose                                                   |
|------------------|-----------------------------------------------------------|
| `my_plugin.json` | Metadata — name, version, target class, method list, etc. |
| `my_plugin.py`   | Engine — the actual Python functions                      |

When you **register** a plugin, both files are copied into `~/.cozy_kit/plugins/`. From that point on, only the stored copies are used — you can delete the originals. When you **enable** a plugin, its functions are patched directly onto the target cozy-kit class at runtime.

```
register ──► copy to store ──► on_install()
enable   ──► patch class   ──► on_enable()
disable  ──► unpatch class ──► on_disable()
remove   ──► delete store  ──► on_uninstall()
upgrade  ──► disable (old) ──► re-register ──► re-enable (new)
```

---

## Quick Start

```bash
pip install cozy-kit
```

```python
from cozy_kit.plugins import plugin, add_plugin
from cozy_kit import Greeting

# 1. Register (one-time)
plugin(metadata="my_plugin.json", engine="my_plugin.py")

# 2. Enable
add_plugin("my_plugin")

# 3. Use the new method on the class
g = Greeting(name="Youssef")
g.say_howdy()
```

---

## Creating a Plugin

### The Metadata File

Create `my_plugin.json`:

```json
{
  "name": "my_plugin",
  "version": "1.0.0",
  "description": "Adds a friendly howdy greeting",
  "author": "Your Name",
  "license": "MIT",
  "target": "Greeting",
  "methods": ["say_howdy"]
}
```

### All Metadata Fields

| Field                  | Required | Type         | Description                                                                                                          |
|------------------------|----------|--------------|----------------------------------------------------------------------------------------------------------------------|
| `name`                 | Yes      | string       | Unique plugin identifier. Alphanumeric, underscores, hyphens only. Must match the `name` field in your PyPI package. |
| `version`              | Yes      | string       | PEP 440 version string, e.g. `"1.0.0"`                                                                               |
| `description`          | Yes      | string       | Short summary of what the plugin does                                                                                |
| `author`               | Yes      | string       | Your name or email                                                                                                   |
| `methods`              | Yes      | list[string] | Function names the engine file must define                                                                           |
| `license`              | No       | string       | SPDX identifier, e.g. `"MIT"`, `"Apache-2.0"`                                                                        |
| `target`               | No       | string       | cozy-kit class to patch. Omit for standalone plugins.                                                                |
| `dependencies`         | No       | list[string] | Other cozy-kit plugins this depends on, with optional PEP 440 version specifiers, e.g. `["base_plugin>=1.0,<2.0"]`  |
| `min_cozy_kit_version` | No       | string       | Minimum cozy-kit version required, e.g. `"1.0.6"`                                                                    |
| `python_requires`      | No       | string       | Python version specifier, e.g. `">=3.10"`                                                                            |
| `tags`                 | No       | list[string] | Keywords for filtering, e.g. `["text", "formatter"]`                                                                 |
| `conflict_with`        | No       | list[string] | Plugin names that cannot be active at the same time as this one                                                      |
| `$schema`              | No       | string       | Point to `plugin-schema.json` for IDE autocomplete (optional)                                                        |

**Full example:**

```json
{
  "name": "fancy_greetings",
  "version": "2.1.0",
  "description": "Adds emoji-rich greeting methods to the Greeting class",
  "author": "Jane Dev <jane@example.com>",
  "license": "MIT",
  "target": "Greeting",
  "methods": ["say_howdy", "wave", "fist_bump"],
  "dependencies": ["base_greeting_utils>=1.0"],
  "min_cozy_kit_version": "1.0.6",
  "python_requires": ">=3.9",
  "tags": ["greeting", "emoji", "fun"],
  "conflict_with": ["minimal_greetings"]
}
```

### The Engine File

Create `my_plugin.py`. Each function listed in `"methods"` must be defined here.

**For target plugins** (patched onto a class), the first argument is `self` — the class instance:

```python
def say_howdy(self):
    print(f"Howdy, {self.name}! 🤠")

def wave(self):
    print(f"👋 Hey there, {self.name}!")

def fist_bump(self, other_name: str) -> str:
    return f"{self.name} 👊 {other_name}"
```

**For standalone plugins** (no target), functions take whatever arguments make sense:

```python
def generate_haiku(topic: str) -> str:
    # ... your logic
    return haiku

def word_frequency(text: str) -> dict:
    # ... your logic
    return counts
```

### Lifecycle Hooks

You can optionally define these functions in your engine file. They are called automatically at each stage and receive a `PluginContext` object.

```python
def on_install(ctx):
    """Called once when the plugin is first registered."""
    print(f"Thanks for installing {ctx.name} v{ctx.version}!")

def on_update(ctx, old_version: str):
    """Called when the plugin is re-registered with overwrite=True."""
    print(f"Updated from v{old_version} to v{ctx.version}")

def on_enable(ctx):
    """Called each time the plugin is enabled in a session."""
    print(f"{ctx.name} is now active!")

def on_disable(ctx):
    """Called each time the plugin is disabled."""
    print(f"{ctx.name} has been disabled.")

def on_uninstall(ctx):
    """Called once just before the plugin is fully removed."""
    print(f"Goodbye from {ctx.name}!")
```

**`PluginContext` attributes:**

| Attribute          | Type        | Value                |
|--------------------|-------------|----------------------|
| `ctx.name`         | str         | Plugin name          |
| `ctx.version`      | str         | Plugin version       |
| `ctx.description`  | str         | Plugin description   |
| `ctx.author`       | str         | Plugin author        |
| `ctx.methods`      | list[str]   | List of method names |
| `ctx.target`       | str or None | Target class name    |
| `ctx.dependencies` | list[str]   | Dependency list      |

> Hooks time out after **5 seconds**. A timed-out hook raises `PluginLifecycleError` and, for `on_enable`, triggers a full rollback.

### Target Classes

These are the cozy-kit classes a plugin can patch:

| Target name (in JSON)  | Python class         | Module                 |
|------------------------|----------------------|------------------------|
| `"Greeting"`           | `Greeting`           | `cozy_kit.greeting`    |
| `"Timer"`              | `Timer`              | `cozy_kit.timer`       |
| `"TextEditor"`         | `TextEditor`         | `cozy_kit.text_studio` |
| `"TextCustomizations"` | `TextCustomizations` | `cozy_kit.text_studio` |
| `"CozyUI"`             | `CozyUI`             | `cozy_kit.ui`          |
| `"SMTPMailer"`         | `SMTPMailer`         | `cozy_kit.mailer`      |

You can also register a custom class as a target from Python:

```python
from cozy_kit.plugins import register_target

class MyClass:
    pass

register_target("MyClass", MyClass)
# Now plugins can use "target": "MyClass" in their metadata
```

### Standalone Plugins

Omit `"target"` from the metadata. The functions are stored and accessed via `get_plugin_functions()`:

```json
{
  "name": "text_tools",
  "version": "1.0.0",
  "description": "Standalone text utility functions",
  "author": "Jane Dev",
  "methods": ["word_frequency", "generate_haiku"]
}
```

```python
from cozy_kit.plugins import add_plugin, get_plugin_functions

add_plugin("text_tools")
fns = get_plugin_functions("text_tools")
print(fns["word_frequency"]("hello world hello"))
```

---

## Testing Your Plugin Locally

```bash
# 1. Validate without registering (catches errors early)
cozy-plugins validate my_plugin.json my_plugin.py

# 2. Register it
cozy-plugins register my_plugin.json my_plugin.py

# 3. Quick Python test
python -c "
from cozy_kit.plugins import add_plugin
from cozy_kit import Greeting
add_plugin('my_plugin')
g = Greeting(name='Test')
g.say_howdy()
"

# 4. If you make changes, re-register with --overwrite
cozy-plugins register my_plugin.json my_plugin.py --overwrite

# 5. Remove when done testing
cozy-plugins remove my_plugin
```

---

## Publishing to PyPI

Publishing lets anyone install your plugin with a single command via the marketplace.

### Package Structure

```
cozy-kit-plugin-fancy-greetings/
├── pyproject.toml
├── README.md
└── cozy_kit_plugin_fancy_greetings/
    ├── __init__.py
    ├── fancy_greetings.json    ← your metadata file
    └── fancy_greetings.py      ← your engine file
```

The `__init__.py` exposes the paths so the marketplace installer can find them automatically:

```python
# cozy_kit_plugin_fancy_greetings/__init__.py
from pathlib import Path

METADATA = str(Path(__file__).parent / "fancy_greetings.json")
ENGINE   = str(Path(__file__).parent / "fancy_greetings.py")
```

This lets users register with one line, and is what `cozy-plugins marketplace install` uses internally:

```python
import cozy_kit_plugin_fancy_greetings as p
from cozy_kit.plugins import plugin
plugin(metadata=p.METADATA, engine=p.ENGINE)
```

### Naming Convention

Follow this convention so your plugin is discoverable:

| Thing                   | Convention               | Example                           |
|-------------------------|--------------------------|-----------------------------------|
| PyPI package name       | `cozy-kit-plugin-<name>` | `cozy-kit-plugin-fancy-greetings` |
| Python module name      | `cozy_kit_plugin_<name>` | `cozy_kit_plugin_fancy_greetings` |
| Plugin `"name"` in JSON | `<name>` (no prefix)     | `fancy_greetings`                 |

### pyproject.toml for Plugin Packages

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "cozy-kit-plugin-fancy-greetings"
version = "1.0.0"
description = "Adds emoji-rich greeting methods to cozy-kit's Greeting class"
authors = [{ name = "Jane Dev", email = "jane@example.com" }]
license = { text = "MIT" }
requires-python = ">=3.9"
dependencies = ["cozy-kit>=1.0.6"]
keywords = [
    "cozy-kit-plugin",    # ← required for discovery
    "cozy-kit",
    "greeting",
    "emoji",
]
classifiers = [
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Topic :: Software Development :: Libraries",
]

[project.urls]
Homepage = "https://github.com/yourname/cozy-kit-plugin-fancy-greetings"

[tool.setuptools.package-data]
cozy_kit_plugin_fancy_greetings = ["*.json"]
```

### Making Your Plugin Discoverable

1. **Name your package** `cozy-kit-plugin-<something>` — the marketplace matches on this prefix automatically.
2. **Add the keyword** `cozy-kit-plugin` to your `keywords` list in `pyproject.toml`.
3. **Write a clear description** — it appears in marketplace results.

### Publishing Steps

```bash
pip install build twine

# Build
python -m build

# Upload to PyPI
twine upload dist/*
```

Once published, your plugin is immediately installable via `cozy-plugins marketplace install <name>`. To appear in the curated marketplace list with verified status, tags, and richer metadata, see [Getting Listed in the Marketplace](#getting-listed-in-the-marketplace).

---

## Marketplace

The built-in marketplace lets users browse, install, and upgrade plugins without leaving the terminal. It combines a curated GitHub registry with live PyPI version data.

### Browsing the Marketplace

```bash
# List all available plugins
cozy-plugins marketplace list

# Filter by tag
cozy-plugins marketplace list --tag greeting

# Search by keyword
cozy-plugins marketplace search emoji

# Show full details for one plugin
cozy-plugins marketplace info fancy-greetings

# Check which of your installed plugins have newer versions
cozy-plugins marketplace updates
```

### Installing from the Marketplace

```bash
# Install and register in one command
cozy-plugins marketplace install fancy-greetings

# Skip adding to autoload
cozy-plugins marketplace install fancy-greetings --no-autoload

# Replace an already-registered plugin
cozy-plugins marketplace install fancy-greetings --overwrite
```

### Upgrading Plugins

When a plugin author publishes a new version to PyPI, `marketplace updates` detects it automatically — version data always comes from live PyPI search, so no manual registry update is needed.

```bash
# See what's outdated
cozy-plugins marketplace updates

# Upgrade one plugin
cozy-plugins marketplace upgrade fancy-greetings

# Upgrade everything at once
cozy-plugins marketplace upgrade --all
```

`upgrade` is smarter than re-installing: if the plugin is currently enabled it atomically disables the old engine, registers the new one, and re-enables it in the same session — calling `on_disable`, `on_update`, and `on_enable` in the correct order.

### Getting Listed in the Marketplace

The curated registry lives at `github.com/youssefahmed2017/cozy-kit-marketplace`. To get listed:

1. Publish your plugin to PyPI following the naming convention above.
2. Open a pull request adding your plugin to `marketplace.json`:

```json
{
  "name": "fancy_greetings",
  "package": "cozy-kit-plugin-fancy-greetings",
  "description": "Adds emoji-rich greeting methods to the Greeting class",
  "author": "Jane Dev",
  "license": "MIT",
  "target": "Greeting",
  "tags": ["greeting", "emoji", "fun"]
}
```

> The `"version"` field is intentionally absent — versions are always pulled live from PyPI. You only need to update your registry entry when metadata (description, tags, target) changes.

After review, a maintainer sets `"verified": true`, which adds a ✓ badge next to your plugin in `marketplace list`.

---

## CLI Reference

All commands are available as `cozy-plugins <command>`.

### `list`

```
cozy-plugins list [--json] [--tag TAG]
```

Lists all registered plugins.

| Flag        | Description                          |
|-------------|--------------------------------------|
| `--json`    | Print raw JSON instead of the table  |
| `--tag TAG` | Show only plugins with the given tag |

---

### `info`

```
cozy-plugins info <name>
```

Prints the full stored metadata JSON for a plugin.

---

### `register`

```
cozy-plugins register <metadata> <engine> [--overwrite] [--no-autoload]
```

Registers a plugin from local files. Copies them into `~/.cozy_kit/plugins/`.

| Flag            | Description                                                          |
|-----------------|----------------------------------------------------------------------|
| `--overwrite`   | Replace an existing plugin with the same name. Triggers `on_update`. |
| `--no-autoload` | Register without adding to the autoload list.                        |

---

### `remove`

```
cozy-plugins remove <name>
```

Calls `on_uninstall`, then deletes the plugin from the store and registry.

---

### `enable`

```
cozy-plugins enable <name>
```

Adds a registered plugin to the autoload list so it is re-enabled automatically on next startup.

---

### `disable`

```
cozy-plugins disable <name>
```

Removes a plugin from the autoload list. Does not delete it.

---

### `upgrade`

```
cozy-plugins upgrade <name> <metadata> <engine>
```

Upgrades a registered plugin from **local files** atomically. If the plugin is currently enabled:
1. Disables it (`on_disable` fires on the old engine)
2. Registers the new engine (`on_update` fires)
3. Re-enables it (`on_enable` fires on the new engine)

For marketplace-installed plugins, use `cozy-plugins marketplace upgrade` instead.

---

### `validate`

```
cozy-plugins validate <metadata> <engine>
```

Validates a plugin without registering it. Checks metadata structure, field types, version specifiers, engine syntax, and that the engine defines every method listed in metadata. Exits `0` on success, `1` on failure.

---

### `stubs`

```
cozy-plugins stubs [name ...]
```

Generates `.pyi` stub files next to each target class's `.py` file so IDEs (PyCharm, VS Code, mypy) recognize the dynamically added methods. Pass plugin names to limit which stubs are generated; omit to generate for all registered plugins.

---

### `discover`

```
cozy-plugins discover [name]
```

Searches PyPI directly for published cozy-kit plugins. For the richer curated experience, use `marketplace list` instead.

---

### `marketplace list`

```
cozy-plugins marketplace list [--tag TAG] [--json] [--refresh]
```

Lists plugins from the curated registry merged with live PyPI version data. Verified plugins are marked with ✓.

| Flag        | Description                                         |
|-------------|-----------------------------------------------------|
| `--tag TAG` | Filter by tag, name, or description keyword         |
| `--json`    | Print raw JSON                                      |
| `--refresh` | Bypass the local cache (TTL 1 hour) and re-fetch    |

---

### `marketplace search`

```
cozy-plugins marketplace search <query> [--refresh]
```

Searches the marketplace index by keyword. Results are ranked: name matches first, then tag matches, then description matches.

---

### `marketplace info`

```
cozy-plugins marketplace info <name>
```

Shows full details for a plugin: version, author, license, target class, tags, verified status, and PyPI URL. Pulls from both the curated registry and live PyPI metadata.

---

### `marketplace updates`

```
cozy-plugins marketplace updates [--refresh]
```

Compares the installed version of each registered plugin against the latest version on PyPI. Lists anything that has a newer version available.

---

### `marketplace install`

```
cozy-plugins marketplace install <name> [--overwrite] [--no-autoload]
```

Installs a plugin from PyPI and registers it in one command. Accepts short name (`fancy-greetings`), underscore form (`fancy_greetings`), or full package name (`cozy-kit-plugin-fancy-greetings`).

---

### `marketplace upgrade`

```
cozy-plugins marketplace upgrade [name] [--all]
```

Upgrades an installed marketplace plugin to the latest version on PyPI. Performs an atomic swap: disables the old engine, registers the new one, re-enables — firing `on_disable`, `on_update`, and `on_enable` in the correct order.

| Flag    | Description                                    |
|---------|------------------------------------------------|
| `--all` | Upgrade every installed plugin with a newer version available |

---

## Python API Reference

```python
from cozy_kit.plugins import (
    plugin,                    # Register a plugin from local files
    add_plugin,                # Enable a plugin (patch the target class)
    disable_plugin,            # Unpatch and disable a plugin
    remove_plugin,             # Disable + delete from store
    upgrade_plugin,            # Atomically upgrade from local files
    install_from_marketplace,  # pip install + register in one call
    upgrade_from_marketplace,  # pip upgrade + atomic swap in one call
    get_plugin_functions,      # Get callables for a standalone plugin
    register_target,           # Register a custom class as a plugin target
    list_plugins,              # Return the registry dict
    autoload_plugins,          # Re-enable all plugins from the last session
    validate_plugin,           # Dry-run validation → ValidationResult
    generate_stubs,            # Write .pyi stub files
    status,                    # Snapshot of current runtime state
    get_index_entry,           # Look up one plugin in the marketplace index
)
```

### `plugin(metadata, engine, overwrite=False) → PluginManifest`

Registers a plugin from local files.

- `metadata` — path to the `.json` file (`.json` extension optional)
- `engine` — path to the `.py` file (`.py` extension optional)
- `overwrite` — if `True`, replaces an existing plugin with the same name and calls `on_update`

### `add_plugin(name) → None`

Enables a registered plugin. Resolves dependencies, verifies file integrity, checks compatibility, detects conflicts, patches the target class, and calls `on_enable`. Adds the plugin to the autoload list on success.

### `disable_plugin(name) → None`

Removes a plugin's patches from its target class and calls `on_disable`. The plugin stays registered. No-op if the plugin is not enabled.

### `remove_plugin(name) → None`

Disables the plugin, calls `on_uninstall`, then deletes it from the store.

### `upgrade_plugin(name, metadata, engine) → PluginManifest`

Upgrades a plugin from **local files** without losing its enabled state. See the `upgrade` CLI command for the step-by-step flow. For marketplace plugins, prefer `upgrade_from_marketplace()`.

### `install_from_marketplace(name, overwrite=False, autoload=True) → PluginManifest`

Installs a cozy-kit plugin from PyPI in one call: runs `pip install`, imports the package to find `METADATA` and `ENGINE` paths, then calls `plugin()`.

### `upgrade_from_marketplace(name) → PluginManifest`

Upgrades an installed marketplace plugin to the latest PyPI version. Runs `pip install --upgrade`, reimports the package for fresh paths, then calls `upgrade_plugin()` for an atomic disable → re-register → re-enable. The plugin must already be registered.

### `get_index_entry(name) → dict | None`

Returns the cached marketplace index entry for a plugin by short name, underscore name, or full package name. Returns `None` if the plugin is not in the index or the index cannot be fetched.

### `get_plugin_functions(name) → dict[str, Callable]`

Returns `{"function_name": <callable>}` for a standalone plugin.

### `autoload_plugins() → dict[str, Exception | None]`

Re-enables all plugins that were active in the previous session. Failures are caught per-plugin — a broken plugin does not block the others. Returns a dict of `name → None` (success) or the exception that occurred.

### `validate_plugin(metadata, engine) → ValidationResult`

Dry-run validation. Returns a `ValidationResult(errors, warnings)` named tuple. Check `.is_valid` to see if the plugin is safe to register.

```python
from cozy_kit.plugins import validate_plugin

result = validate_plugin("my_plugin.json", "my_plugin.py")
if result.is_valid:
    print("Good to go!")
else:
    for err in result.errors:
        print(f"ERROR: {err}")
for warn in result.warnings:
    print(f"WARNING: {warn}")
```

### `status() → dict`

Returns the current runtime state:

```python
{
    "enabled": ["plugin_a", "plugin_b"],
    "standalone": {"text_tools": ["word_frequency", "generate_haiku"]},
    "method_ownership": {"Greeting": {"say_howdy": "fancy_greetings"}}
}
```
