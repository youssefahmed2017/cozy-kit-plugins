from cozy_kit._internal.errors.inheritance_errors import CozyKitPluginSystemError


class InvalidMetadataError(CozyKitPluginSystemError):
    """Raised when plugin metadata is invalid or missing required fields."""


class PluginNotFoundError(CozyKitPluginSystemError):
    """Raised when a plugin cannot be found in the registry."""


class PluginAlreadyExistsError(CozyKitPluginSystemError):
    """Raised when registering a plugin whose name is already taken."""


class EngineNotFoundError(CozyKitPluginSystemError):
    """Raised when the engine file path does not exist."""


class InvalidEngineError(CozyKitPluginSystemError):
    """Raised when the engine file fails to load or is missing declared methods."""


class TargetClassNotFoundError(CozyKitPluginSystemError):
    """Raised when the requested target class cannot be resolved."""


class PluginLifecycleError(CozyKitPluginSystemError):
    """Raised when a lifecycle hook (on_install, on_enable, on_disable, on_uninstall) raises."""


class MissingDependencyError(CozyKitPluginSystemError):
    """Raised when a plugin's required dependency is not registered."""


class CircularDependencyError(CozyKitPluginSystemError):
    """Raised when plugins form a circular dependency chain."""


class MethodCollisionError(CozyKitPluginSystemError):
    """Raised when two different plugins try to add the same method to the same target class."""


class PluginIntegrityError(CozyKitPluginSystemError):
    """Raised when an engine file's SHA-256 does not match the value stored at registration time."""


class PluginCompatibilityError(CozyKitPluginSystemError):
    """Raised when a plugin's python_requires or min_cozy_kit_version is not satisfied."""


class PluginConflictError(CozyKitPluginSystemError):
    """Raised when enabling a plugin that conflicts with an already-enabled plugin."""


class MarketplaceError(CozyKitPluginSystemError):
    """Raised when a marketplace operation fails (network, pip, or naming-convention errors)."""
