import importlib.util
import sys
from types import ModuleType

from cozy_kit._internal.errors.plugin_errors import InvalidEngineError


def load_module_from_path(path: str, module_name: str) -> ModuleType:
    """Dynamically load a Python file as a module."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise InvalidEngineError(f"Cannot create module spec from: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        del sys.modules[module_name]
        raise InvalidEngineError(f"Error executing engine '{path}': {exc}") from exc

    return module
