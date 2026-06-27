try:
    import packaging  # noqa: F401
except ImportError:
    raise ImportError(
        "cozy-kit's plugin system requires optional dependencies.\n"
        'Install them with:  pip install "cozy-kit[plugins]"'
    ) from None

"""
cozy_kit.plugins — Plugin system for cozy-kit.

Quick start
-----------
Developer (registering a plugin):
    from cozy_kit.plugins import plugin
    plugin(metadata="./myplugin.json", engine="./myplugin")

End-user (enabling a plugin):
    from cozy_kit.plugins import add_plugin
    add_plugin("myplugin")

Disabling / removing:
    from cozy_kit.plugins import disable_plugin, remove_plugin
    disable_plugin("myplugin")   # removes patches, keeps registry entry
    remove_plugin("myplugin")    # calls on_uninstall then deletes everything

Listing:
    from cozy_kit.plugins import list_plugins
    print(list_plugins())
"""

from cozy_kit.plugins.core.publisher import plugin
from cozy_kit.plugins.core.installer import (
    add_plugin,
    disable_plugin,
    remove_plugin,
    upgrade_plugin,
    get_plugin_functions,
    get_cli_entry,
    list_clis,
    register_target,
    status,
    autoload_plugins,
)
from cozy_kit.plugins.core.registry import list_plugins, unregister_plugin
from cozy_kit.plugins.core.stubgen import generate_stubs
from cozy_kit.plugins.core.validator import validate_plugin
from cozy_kit.plugins.core.marketplace import (
    install_from_marketplace,
    upgrade_from_marketplace,
    get_index_entry,
)
from cozy_kit.plugins.core._builtins import ensure_builtins_installed
from cozy_kit._internal.errors.plugin_errors import (
    InvalidMetadataError,
    PluginNotFoundError,
    PluginAlreadyExistsError,
    EngineNotFoundError,
    InvalidEngineError,
    TargetClassNotFoundError,
    PluginLifecycleError,
    MissingDependencyError,
    CircularDependencyError,
    MethodCollisionError,
    PluginIntegrityError,
    PluginCompatibilityError,
    PluginConflictError,
    MarketplaceError,
    PluginCLIError,
)

from cozy_kit._internal.errors.inheritance_errors import CozyKitPluginSystemError

__all__ = [
    "plugin",
    "add_plugin",
    "disable_plugin",
    "remove_plugin",
    "get_plugin_functions",
    "get_cli_entry",
    "list_clis",
    "register_target",
    "list_plugins",
    "unregister_plugin",
    "generate_stubs",
    "status",
    "autoload_plugins",
    "validate_plugin",
    "upgrade_plugin",
    "install_from_marketplace",
    "upgrade_from_marketplace",
    "get_index_entry",
    "ensure_builtins_installed",
    "CozyKitPluginSystemError",
    "InvalidMetadataError",
    "PluginNotFoundError",
    "PluginAlreadyExistsError",
    "EngineNotFoundError",
    "InvalidEngineError",
    "TargetClassNotFoundError",
    "PluginLifecycleError",
    "MissingDependencyError",
    "CircularDependencyError",
    "MethodCollisionError",
    "PluginIntegrityError",
    "PluginCompatibilityError",
    "PluginConflictError",
    "MarketplaceError",
    "PluginCLIError",
]
