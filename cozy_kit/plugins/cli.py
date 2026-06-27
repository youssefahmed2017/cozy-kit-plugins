"""Command-line interface for the cozy-kit plugin system.

Usage:
    cozy-plugins <command> [args]

Commands:
    list      [--json] [--tag TAG]         List registered plugins
    info      <name>                       Show full plugin metadata
    register  <metadata> <engine>          Register a plugin from local files
              [--overwrite] [--no-autoload]
    remove    <name>                       Unregister and delete a plugin
    enable    <name>                       Mark a plugin for autoload
    disable   <name>                       Remove a plugin from autoload
    upgrade   <name> <metadata> <engine>   Upgrade a registered plugin
    validate  <metadata> <engine>          Dry-run validation without registering
    stubs     [name ...]                   Generate .pyi stub files
    discover  [name]                       List all plugins, or look up one by name
"""

import argparse
import json
import sys

from rich.console import Console

console = Console()


def _cmd_list(args) -> int:
    from cozy_kit.plugins.core.registry import get_registry, get_autoload_list
    from rich.table import Table

    registry = get_registry()
    autoload = set(get_autoload_list())

    if args.tag:
        registry = {
            n: info for n, info in registry.items() if args.tag in info.get("tags", [])
        }

    if not registry:
        msg = (
            f"No plugins registered with tag [bold]{args.tag}[/bold]."
            if args.tag
            else "No plugins registered."
        )
        console.print(f"[yellow]{msg}[/yellow]")
        return 0

    if args.json:
        print(json.dumps(registry, indent=2))
        return 0

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Name", style="cyan bold", no_wrap=True)
    table.add_column("Version", style="bright_white")
    table.add_column("Target", style="bright_white")
    table.add_column("Tags", style="dim")
    table.add_column("Autoload", style="green")
    table.add_column("CLIs", style="dim")

    for name, info in sorted(registry.items()):
        target = info.get("target") or "(standalone)"
        tag_str = ", ".join(info.get("tags", []))
        marker = "[green]yes[/green]" if name in autoload else ""
        raw_clis = info.get("clis") or []
        cli_names = ", ".join(
            sorted(raw_clis if isinstance(raw_clis, list) else raw_clis.keys())
        )
        badges = ""
        if info.get("official"):
            badges += "[gold1]★[/gold1] "
        if info.get("builtin"):
            badges += "[bright_blue]⬡[/bright_blue] "
        name_cell = f"{badges}[cyan bold]{name}[/cyan bold]"
        table.add_row(
            name_cell, info.get("version", ""), target, tag_str, marker, cli_names
        )

    console.print(table)
    return 0


def _cmd_info(args) -> int:
    from cozy_kit.plugins.core.registry import fetch_plugin
    from cozy_kit._internal.errors.plugin_errors import PluginNotFoundError
    from rich.json import JSON
    from rich.panel import Panel

    try:
        data = fetch_plugin(args.name)
    except PluginNotFoundError as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}", file=sys.stderr)
        return 1

    badges = ""
    if data.get("official"):
        badges += " [gold1]★ OFFICIAL[/gold1]"
    if data.get("builtin"):
        badges += " [bright_blue]⬡ BUILT-IN[/bright_blue]"
    console.print(
        Panel(
            JSON(json.dumps(data, indent=2)),
            title=f"[cyan bold]{args.name}[/cyan bold]{badges}",
            border_style="magenta",
        )
    )
    return 0


def _cmd_install(args) -> int:
    from cozy_kit.plugins.core.publisher import plugin
    from cozy_kit.plugins.core.registry import set_autoload
    from cozy_kit._internal.errors.inheritance_errors import (
        CozyKitPluginSystemError as PluginSystemError,
    )

    try:
        manifest = plugin(
            metadata=args.metadata,
            engine=args.engine,
            overwrite=args.overwrite,
        )
    except PluginSystemError as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1

    if not args.no_autoload:
        set_autoload(manifest.name, True)
        console.print(
            f"[green]✓[/green] Installed [cyan bold]{manifest.name}[/cyan bold] "
            f"[bright_white]v{manifest.version}[/bright_white] "
            f"[dim](marked for autoload)[/dim]"
        )
    else:
        console.print(
            f"[green]✓[/green] Installed [cyan bold]{manifest.name}[/cyan bold] "
            f"[bright_white]v{manifest.version}[/bright_white]"
        )

    return 0


def _cmd_remove(args) -> int:
    from cozy_kit.plugins.core.registry import unregister_plugin
    from cozy_kit._internal.errors.plugin_errors import PluginNotFoundError

    try:
        unregister_plugin(args.name)
    except PluginNotFoundError as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1

    console.print(
        f"[yellow]✗[/yellow] Removed plugin [cyan bold]{args.name}[/cyan bold]."
    )
    return 0


def _cmd_enable(args) -> int:
    from cozy_kit.plugins.core.registry import get_registry, set_autoload

    if args.name not in get_registry():
        console.print(
            f"[red bold]Error:[/red bold] Plugin [cyan bold]{args.name}[/cyan bold] is not registered."
        )
        return 1

    set_autoload(args.name, True)
    console.print(
        f"[green]✓[/green] Plugin [cyan bold]{args.name}[/cyan bold] will be autoloaded on next startup."
    )
    return 0


def _cmd_disable(args) -> int:
    from cozy_kit.plugins.core.registry import set_autoload

    set_autoload(args.name, False)
    console.print(
        f"[yellow]–[/yellow] Plugin [cyan bold]{args.name}[/cyan bold] removed from autoload list."
    )
    return 0


def _cmd_validate(args) -> int:
    from cozy_kit.plugins.core.validator import validate_plugin

    result = validate_plugin(args.metadata, args.engine)

    for w in result.warnings:
        console.print(f"[yellow bold]WARNING:[/yellow bold] {w}")
    for e in result.errors:
        console.print(f"[red bold]ERROR:[/red bold]   {e}")

    if result.is_valid:
        suffix = (
            f" [dim]({len(result.warnings)} warning(s))[/dim]"
            if result.warnings
            else ""
        )
        console.print(f"[green bold]Validation PASSED[/green bold]{suffix}.")
        return 0

    console.print(
        f"\n[red bold]Validation FAILED[/red bold] [dim]({len(result.errors)} error(s))[/dim]."
    )
    return 1


def _cmd_upgrade(args) -> int:
    from cozy_kit.plugins.core.installer import upgrade_plugin
    from cozy_kit._internal.errors.inheritance_errors import (
        CozyKitPluginSystemError as PluginSystemError,
    )

    try:
        manifest = upgrade_plugin(
            name=args.name, metadata=args.metadata, engine=args.engine
        )
    except PluginSystemError as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1

    console.print(
        f"[green]✓[/green] Upgraded [cyan bold]{manifest.name}[/cyan bold] "
        f"to [bright_white]v{manifest.version}[/bright_white]."
    )
    return 0


def _cmd_discover(args) -> int:
    from cozy_kit.plugins.core.marketplace import (
        fetch_index,
        get_plugin_pypi_info,
        MarketplaceError,
    )
    from cozy_kit.plugins.core.registry import get_registry
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table

    plugin_name = args.plugin_name

    # discover <name> — full details for one specific plugin
    if plugin_name:
        try:
            info = get_plugin_pypi_info(plugin_name)
        except MarketplaceError as exc:
            console.print(f"[red bold]Error:[/red bold] {exc}")
            return 1

        details = (
            f"[bold]Name[/bold]        [cyan bold]{info['name']}[/cyan bold]\n"
            f"[bold]Version[/bold]     [bright_white]{info['version']}[/bright_white]\n"
            f"[bold]Description[/bold] {info['summary']}\n"
            f"[bold]Author[/bold]      {info['author']}\n"
            f"[bold]License[/bold]     {info.get('license') or 'N/A'}\n"
            f"[bold]PyPI[/bold]        [link={info['package_url']}]{info['package_url']}[/link]\n\n"
            f"[bold]Install[/bold]     [dim]pip install {info['name']}[/dim]\n"
            f"[bold]Register[/bold]    [dim]cozy-plugins install <metadata.json> <engine.py>[/dim]"
        )
        console.print(
            Panel(
                details,
                title=f"[magenta bold]{plugin_name}[/magenta bold]",
                border_style="cyan",
            )
        )
        return 0

    # discover (no args) — local registry + PyPI
    registry = get_registry()

    console.print(Rule("[bold magenta]Installed plugins[/bold magenta]"))
    if registry:
        table = Table(show_header=True, header_style="bold magenta", box=None)
        table.add_column("Name", style="cyan bold")
        table.add_column("Version", style="bright_white")
        table.add_column("Target", style="dim bold")
        for name, info in sorted(registry.items()):
            target = info.get("target") or "standalone"
            table.add_row(name, f"v{info.get('version', '?')}", target)
        console.print(table)
    else:
        console.print("  [dim](none)[/dim]")

    console.print(Rule("[bold magenta]Available on PyPI[/bold magenta]"))
    try:
        index = fetch_index()
        if not index:
            console.print("  [dim](none found)[/dim]")
        else:
            table = Table(show_header=True, header_style="bold magenta", box=None)
            table.add_column("Name", style="cyan bold")
            table.add_column("Version", style="bright_white")
            table.add_column("Description", style="dim")
            for entry in index:
                table.add_row(
                    entry["package"],
                    f"v{entry.get('version', '?')}",
                    entry.get("description", ""),
                )
            console.print(table)
    except MarketplaceError as exc:
        console.print(f"  [yellow](could not reach PyPI: {exc})[/yellow]")

    console.print(
        f"\n[dim]Run [/dim][cyan]cozy-plugins discover <name>[/cyan]"
        f"[dim] for details on a specific plugin.[/dim]"
    )
    return 0


def _cmd_marketplace_list(args) -> int:
    from cozy_kit.plugins.core.marketplace import fetch_index, MarketplaceError
    from cozy_kit.plugins.core.registry import get_registry
    from rich.table import Table

    try:
        with console.status("Fetching plugin index…", spinner="dots"):
            index = fetch_index(force_refresh=args.refresh)
    except MarketplaceError as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1

    if args.tag:
        tag = args.tag.lower()
        index = [
            e
            for e in index
            if tag in [t.lower() for t in e.get("tags", [])]
            or tag in e.get("name", "").lower()
            or tag in e.get("description", "").lower()
        ]

    if not index:
        msg = (
            f"No plugins found matching tag '[bold]{args.tag}[/bold]'."
            if args.tag
            else "No plugins found on PyPI."
        )
        console.print(f"[yellow]{msg}[/yellow]")
        return 0

    if args.json:
        print(json.dumps(index, indent=2))
        return 0

    registry = get_registry()
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Name", no_wrap=True)
    table.add_column("Version", style="bright_white", no_wrap=True)
    table.add_column("Target", style="dim", no_wrap=True)
    table.add_column("Tags", style="dim")
    table.add_column("Description")
    table.add_column("Installed", style="green", no_wrap=True)

    for entry in index:
        installed_version = registry.get(entry["plugin_name"], {}).get("version", "")
        installed_cell = f"v{installed_version}" if installed_version else ""
        name_cell = (
            f"[green]✓[/green] [cyan bold]{entry['name']}[/cyan bold]"
            if entry.get("verified")
            else f"[cyan]{entry['name']}[/cyan]"
        )
        tags_cell = ", ".join(entry.get("tags", []))
        table.add_row(
            name_cell,
            entry.get("version", ""),
            entry.get("target", ""),
            tags_cell,
            entry.get("description", ""),
            installed_cell,
        )

    console.print(table)
    console.print(
        f"\n[dim][green]✓[/green] = verified by the cozy-kit marketplace  "
        f"· [cyan]cozy-plugins marketplace info <name>[/cyan] · details"
        f"[/dim]"
    )
    return 0


def _cmd_marketplace_search(args) -> int:
    from cozy_kit.plugins.core.marketplace import (
        fetch_index,
        search_plugins,
        MarketplaceError,
    )
    from cozy_kit.plugins.core.registry import get_registry
    from rich.table import Table

    try:
        with console.status("Searching…", spinner="dots"):
            index = fetch_index(force_refresh=args.refresh)
            results = search_plugins(args.query, index)
    except MarketplaceError as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1

    if not results:
        console.print(
            f"[yellow]No plugins matched[/yellow] '[bold]{args.query}[/bold]'."
        )
        return 0

    registry = get_registry()
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Name", style="cyan bold", no_wrap=True)
    table.add_column("Version", style="bright_white")
    table.add_column("Description")
    table.add_column("Installed", style="green", no_wrap=True)

    for entry in results:
        installed_version = registry.get(entry["plugin_name"], {}).get("version", "")
        installed_cell = f"v{installed_version}" if installed_version else ""
        table.add_row(
            entry["name"],
            entry.get("version", ""),
            entry.get("description", ""),
            installed_cell,
        )

    console.print(table)
    return 0


def _cmd_marketplace_info(args) -> int:
    from cozy_kit.plugins.core.marketplace import (
        get_plugin_pypi_info,
        get_index_entry,
        MarketplaceError,
    )
    from cozy_kit.plugins.core.registry import get_registry
    from rich.panel import Panel

    try:
        with console.status(
            f"Fetching info for [bold]{args.name}[/bold]…", spinner="dots"
        ):
            info = get_plugin_pypi_info(args.name)
            idx = get_index_entry(args.name)  # None when not in registry (non-fatal)
    except MarketplaceError as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1

    prefix = "cozy-kit-plugin-"
    short = args.name[len(prefix) :] if args.name.startswith(prefix) else args.name
    plugin_name = short.replace("-", "_")

    registry = get_registry()
    installed = registry.get(plugin_name, {}).get("version", "")

    # Prefer registry values; fall back to PyPI info fields
    author = (idx or {}).get("author") or info.get("author") or "N/A"
    license_str = (idx or {}).get("license") or info.get("license") or "N/A"
    target = (idx or {}).get("target", "")
    tags = ", ".join((idx or {}).get("tags", []))
    verified = (idx or {}).get("verified", False)

    project_urls = info.get("project_urls") or {}
    homepage = project_urls.get("Homepage") or project_urls.get("homepage", "")

    # Optional lines — only rendered when non-empty
    installed_line = (
        f"\n[bold]Installed[/bold]   [green]v{installed}[/green]" if installed else ""
    )
    target_line = f"\n[bold]Target[/bold]      {target}" if target else ""
    tags_line = f"\n[bold]Tags[/bold]        [dim]{tags}[/dim]" if tags else ""
    verified_line = (
        "\n[bold]Verified[/bold]    [green]✓ curated[/green]" if verified else ""
    )
    homepage_line = (
        f"\n[bold]Homepage[/bold]    [link={homepage}]{homepage}[/link]"
        if homepage
        else ""
    )

    body = (
        f"[bold]Package[/bold]     [cyan bold]{info['name']}[/cyan bold]\n"
        f"[bold]Version[/bold]     [bright_white]{info['version']}[/bright_white]"
        f"{installed_line}\n"
        f"[bold]Description[/bold] {info.get('summary', '')}\n"
        f"[bold]Author[/bold]      {author}\n"
        f"[bold]License[/bold]     {license_str}"
        f"{target_line}"
        f"{tags_line}"
        f"{verified_line}"
        f"{homepage_line}\n"
        f"[bold]PyPI[/bold]        [link={info['package_url']}]{info['package_url']}[/link]\n\n"
        f"[bold]Install[/bold]     [dim]cozy-plugins marketplace install {short}[/dim]"
    )
    console.print(
        Panel(body, title=f"[magenta bold]{short}[/magenta bold]", border_style="cyan")
    )
    return 0


def _cmd_marketplace_updates(args) -> int:
    from cozy_kit.plugins.core.marketplace import check_updates, MarketplaceError
    from rich.table import Table

    try:
        with console.status("Checking for updates…", spinner="dots"):
            outdated = check_updates()
    except MarketplaceError as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1

    if not outdated:
        console.print("[green]All installed plugins are up to date.[/green]")
        return 0

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Plugin", style="cyan bold", no_wrap=True)
    table.add_column("Installed", style="dim", no_wrap=True)
    table.add_column("Latest", style="bright_white", no_wrap=True)

    for entry in outdated:
        table.add_row(entry["name"], entry["installed"], entry["latest"])

    console.print(table)
    console.print(
        f"\n[dim]Run [/dim][cyan]cozy-plugins marketplace upgrade --all[/cyan]"
        f"[dim] to upgrade everything at once.[/dim]"
    )
    return 0


def _cmd_marketplace_upgrade(args) -> int:
    from cozy_kit.plugins.core.marketplace import (
        upgrade_from_marketplace,
        check_updates,
        MarketplaceError,
    )
    from cozy_kit._internal.errors.plugin_errors import PluginNotFoundError
    from cozy_kit._internal.errors.inheritance_errors import (
        CozyKitPluginSystemError as PluginSystemError,
    )

    if args.all:
        try:
            with console.status("Checking for updates…", spinner="dots"):
                outdated = check_updates()
        except MarketplaceError as exc:
            console.print(f"[red bold]Error:[/red bold] {exc}")
            return 1

        if not outdated:
            console.print("[green]All installed plugins are up to date.[/green]")
            return 0

        console.print(f"Upgrading [bold]{len(outdated)}[/bold] plugin(s)…\n")
        exit_code = 0
        for entry in outdated:
            pname = entry["name"]
            try:
                with console.status(
                    f"  Upgrading [bold]{pname}[/bold]…", spinner="dots"
                ):
                    manifest = upgrade_from_marketplace(pname)
                console.print(
                    f"  [green]✓[/green] [cyan bold]{manifest.name}[/cyan bold]  "
                    f"[dim]{entry['installed']}[/dim] → [bright_white]v{manifest.version}[/bright_white]"
                )
            except (MarketplaceError, PluginSystemError) as exc:
                console.print(
                    f"  [red bold]✗[/red bold] [cyan bold]{pname}[/cyan bold]: {exc}"
                )
                exit_code = 1

        return exit_code

    if not args.name:
        console.print(
            "[red bold]Error:[/red bold] Specify a plugin name or use [cyan]--all[/cyan]."
        )
        return 1

    try:
        with console.status(f"Upgrading [bold]{args.name}[/bold]…", spinner="dots"):
            manifest = upgrade_from_marketplace(args.name)
    except PluginNotFoundError as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1
    except (MarketplaceError, PluginSystemError) as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1

    console.print(
        f"[green]✓[/green] Upgraded [cyan bold]{manifest.name}[/cyan bold] "
        f"to [bright_white]v{manifest.version}[/bright_white]"
    )
    return 0


def _cmd_marketplace_install(args) -> int:
    from cozy_kit.plugins.core.marketplace import install_from_marketplace
    from cozy_kit._internal.errors.plugin_errors import (
        MarketplaceError,
        PluginAlreadyExistsError,
    )
    from cozy_kit._internal.errors.inheritance_errors import (
        CozyKitPluginSystemError as PluginSystemError,
    )

    prefix = "cozy-kit-plugin-"
    short = args.name[len(prefix) :] if args.name.startswith(prefix) else args.name
    package = f"{prefix}{short}"

    try:
        with console.status(
            f"Installing [bold]{package}[/bold] from PyPI…", spinner="dots"
        ):
            manifest = install_from_marketplace(
                name=args.name,
                overwrite=args.overwrite,
                autoload=not args.no_autoload,
            )
    except PluginAlreadyExistsError:
        console.print(
            f"[yellow]Already registered.[/yellow] "
            f"Use [cyan]--overwrite[/cyan] to replace the existing registration."
        )
        return 1
    except (MarketplaceError, PluginSystemError) as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1

    if manifest is None:
        console.print(
            f"[green]✓[/green] [cyan bold]{short}[/cyan bold] package updated on disk. "
            f"Run [cyan]cozy-plugins marketplace upgrade {short}[/cyan] "
            f"to also update the cozy-kit registration."
        )
        return 0

    suffix = "" if args.no_autoload else " [dim](marked for autoload)[/dim]"
    console.print(
        f"[green]✓[/green] Installed [cyan bold]{manifest.name}[/cyan bold] "
        f"[bright_white]v{manifest.version}[/bright_white]{suffix}"
    )
    return 0


def _cmd_stubs(args) -> int:
    from cozy_kit.plugins.core.stubgen import generate_stubs
    from cozy_kit._internal.errors.inheritance_errors import (
        CozyKitPluginSystemError as PluginSystemError,
    )

    try:
        result = generate_stubs(*args.names) if args.names else generate_stubs()
    except PluginSystemError as exc:
        console.print(f"[red bold]Error:[/red bold] {exc}")
        return 1

    if not result:
        console.print(
            "[yellow]No stubs generated[/yellow] [dim](no target plugins found).[/dim]"
        )
    else:
        for path, cls_name in result.items():
            console.print(
                f"[green]✓[/green] [dim]Written:[/dim] [cyan]{path}[/cyan]  [dim]({cls_name})[/dim]"
            )

    return 0


def build_parser(prog: str = "cozy-plugins") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Manage cozy-kit plugins.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    p = sub.add_parser("list", help="List all registered plugins.")
    p.add_argument("--json", action="store_true", help="Output raw JSON.")
    p.add_argument("--tag", metavar="TAG", default=None, help="Filter by tag.")
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser("info", help="Show full metadata for a plugin.")
    p.add_argument("name", help="Plugin name.")
    p.set_defaults(func=_cmd_info)

    p = sub.add_parser("install", help="Install/Add a plugin from local files.")
    p.add_argument("metadata", help="Path to metadata .json file.")
    p.add_argument("engine", help="Path to engine .py file.")
    p.add_argument(
        "--overwrite", action="store_true", help="Replace existing registration."
    )
    p.add_argument(
        "--no-autoload", action="store_true", help="Skip adding to the autoload list."
    )
    p.set_defaults(func=_cmd_install)

    p = sub.add_parser("remove", help="Unregister and delete a plugin.")
    p.add_argument("name", help="Plugin name.")
    p.set_defaults(func=_cmd_remove)

    p = sub.add_parser("enable", help="Mark a registered plugin for autoload.")
    p.add_argument("name", help="Plugin name.")
    p.set_defaults(func=_cmd_enable)

    p = sub.add_parser("disable", help="Remove a plugin from the autoload list.")
    p.add_argument("name", help="Plugin name.")
    p.set_defaults(func=_cmd_disable)

    p = sub.add_parser("upgrade", help="Upgrade a registered plugin to a new version.")
    p.add_argument("name", help="Plugin name (must match the metadata 'name' field).")
    p.add_argument("metadata", help="Path to the new metadata .json file.")
    p.add_argument("engine", help="Path to the new engine .py file.")
    p.set_defaults(func=_cmd_upgrade)

    p = sub.add_parser("validate", help="Validate a plugin without registering it.")
    p.add_argument("metadata", help="Path to metadata .json file.")
    p.add_argument("engine", help="Path to engine .py file.")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("stubs", help="Generate .pyi stub files for installed plugins.")
    p.add_argument(
        "names", nargs="*", metavar="name", help="Plugin name(s). All if omitted."
    )
    p.set_defaults(func=_cmd_stubs)

    p = sub.add_parser("discover", help="Search PyPI for published cozy-kit plugins.")
    p.add_argument(
        "plugin_name",
        nargs="?",
        default=None,
        metavar="name",
        help="Plugin name to look up (e.g. 'fancy-greetings'). Omit to list all.",
    )
    p.set_defaults(func=_cmd_discover)

    p_market = sub.add_parser(
        "marketplace", help="Browse and install plugins from the marketplace."
    )
    market_sub = p_market.add_subparsers(
        dest="marketplace_command", metavar="<subcommand>"
    )
    market_sub.required = True

    mp = market_sub.add_parser("list", help="List all available plugins.")
    mp.add_argument(
        "--tag",
        metavar="TAG",
        default=None,
        help="Filter by keyword in name or description.",
    )
    mp.add_argument("--json", action="store_true", help="Output raw JSON.")
    mp.add_argument("--refresh", action="store_true", help="Bypass the local cache.")
    mp.set_defaults(func=_cmd_marketplace_list)

    mp = market_sub.add_parser("search", help="Search plugins by keyword.")
    mp.add_argument("query", help="Search term.")
    mp.add_argument("--refresh", action="store_true", help="Bypass the local cache.")
    mp.set_defaults(func=_cmd_marketplace_search)

    mp = market_sub.add_parser("info", help="Show full details for a plugin.")
    mp.add_argument(
        "name", help="Plugin short name (e.g. 'fancy-greetings') or full package name."
    )
    mp.set_defaults(func=_cmd_marketplace_info)

    mp = market_sub.add_parser(
        "updates", help="Check installed plugins for newer versions."
    )
    mp.add_argument("--refresh", action="store_true", help="Bypass the local cache.")
    mp.set_defaults(func=_cmd_marketplace_updates)

    mp = market_sub.add_parser(
        "upgrade",
        help="Upgrade an installed plugin to the latest version on PyPI.",
    )
    mp.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Plugin name to upgrade (short, underscore, or full package form).",
    )
    mp.add_argument(
        "--all",
        action="store_true",
        help="Upgrade every installed plugin that has a newer version available.",
    )
    mp.set_defaults(func=_cmd_marketplace_upgrade)

    mp = market_sub.add_parser(
        "install",
        help="Install a plugin from PyPI and register it in one command.",
    )
    mp.add_argument(
        "name",
        help="Plugin short name (e.g. 'fancy-greetings') or full package name.",
    )
    mp.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the existing registration if the plugin is already registered.",
    )
    mp.add_argument(
        "--no-autoload",
        action="store_true",
        help="Register without adding to the autoload list.",
    )
    mp.set_defaults(func=_cmd_marketplace_install)

    return parser


def main(argv=None) -> int:
    try:
        import packaging  # noqa: F401
    except ImportError:
        console.print(
            "[red bold]Error:[/red bold] cozy-kit's plugin system requires optional dependencies.\n"
            'Install them with:  [cyan]pip install "cozy-kit\\[plugins]"[/cyan]'
        )
        return 1

    from cozy_kit.plugins.core._builtins import ensure_builtins_installed

    ensure_builtins_installed(silent=True)

    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
