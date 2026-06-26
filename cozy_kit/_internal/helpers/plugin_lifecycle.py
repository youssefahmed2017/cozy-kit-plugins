"""Lifecycle hook execution with daemon-thread timeout."""

import logging
import threading

from cozy_kit._internal.errors.plugin_errors import PluginLifecycleError

_log = logging.getLogger("cozy_kit.plugins")

HOOK_TIMEOUT: float = 5.0


def call_hook(
    module, hook_name: str, ctx, plugin_name: str, extra_args: tuple = ()
) -> None:
    """
    Call a lifecycle hook if the engine defines it.

    Runs in a daemon thread so a hung hook never blocks the process indefinitely.
    Raises PluginLifecycleError on timeout or if the hook itself raises.
    extra_args is forwarded as positional arguments after ctx (used by on_update).
    """
    hook = getattr(module, hook_name, None)
    if hook is None:
        return

    _log.debug("Calling %s() for plugin '%s'.", hook_name, plugin_name)

    exc_holder: list = []

    def _run() -> None:
        try:
            hook(ctx, *extra_args)
        except Exception as exc:
            exc_holder.append(exc)

    thread = threading.Thread(
        target=_run,
        daemon=True,
        name=f"cozy-hook-{plugin_name}-{hook_name}",
    )
    thread.start()
    thread.join(timeout=HOOK_TIMEOUT)

    if thread.is_alive():
        raise PluginLifecycleError(
            f"{hook_name}() for '{plugin_name}' timed out after {HOOK_TIMEOUT}s. "
            "The hook is still running as a background thread."
        )
    if exc_holder:
        raise PluginLifecycleError(
            f"{hook_name}() for plugin '{plugin_name}' raised: {exc_holder[0]}"
        ) from exc_holder[0]
