"""Environment subcommand for MobileWorld CLI - Docker container management."""

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from dotenv import dotenv_values
from mobile_world.core.api.env import (
    DEFAULT_IMAGE,
    DEFAULT_NAME_PREFIX,
    ContainerConfig,
    check_image_status,
    check_prerequisites,
    find_available_ports,
    find_next_container_index,
    get_container_info,
    kill_server_in_container,
    launch_container,
    list_containers,
    pull_image,
    remove_containers,
    resolve_container_name,
    restart_server_in_container,
    wait_for_container_ready,
)
from mobile_world.runtime.utils.docker import (
    build_run_command,
    docker_exec_replace,
)

# Create a Rich console instance for better terminal output
console = Console()


def _add_common_options(
    parser: argparse.ArgumentParser, *, image: bool = False, prefix: bool = False
) -> None:
    """Add common options to a subparser to avoid duplication."""
    if prefix:
        parser.add_argument(
            "--name-prefix",
            "--name_prefix",
            "--prefix",
            dest="name_prefix",
            default=DEFAULT_NAME_PREFIX,
            help=f"Name prefix for containers (default: {DEFAULT_NAME_PREFIX})",
        )
    if image:
        parser.add_argument(
            "--image",
            default=DEFAULT_IMAGE,
            help=f"Filter by image name containing this string (default: {DEFAULT_IMAGE})",
        )


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configure the env subcommand parser."""
    env_parser = subparsers.add_parser(
        "env",
        help="Manage Docker environments for MobileWorld",
    )

    # Global verbosity flags for CLI UX
    env_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce output (only warnings and errors)",
    )
    env_parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for DEBUG, -vv for TRACE)",
    )

    env_subparsers = env_parser.add_subparsers(
        dest="env_action",
        help="Environment management actions",
        required=True,
    )

    # Run subcommand
    launch_parser = env_subparsers.add_parser(
        "run",
        help="Launch Docker container(s)",
    )
    launch_parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of containers to launch (default: 1)",
    )
    launch_parser.add_argument(
        "--backend-start-port",
        "--backend_start_port",
        dest="backend_start_port",
        type=int,
        default=6800,
        help="Starting backend port number (default: 6800)",
    )
    launch_parser.add_argument(
        "--viewer-start-port",
        "--viewer_start_port",
        dest="viewer_start_port",
        type=int,
        default=7860,
        help="Starting viewer port number (default: 7860)",
    )
    launch_parser.add_argument(
        "--adb-start-port",
        "--adb_start_port",
        dest="adb_start_port",
        type=int,
        default=5556,
        help="Starting ADB port number (default: 5556)",
    )
    _add_common_options(launch_parser, prefix=True)
    launch_parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help="Docker image to use (default: mobile_world:latest)",
    )
    launch_parser.add_argument(
        "--detach",
        action="store_true",
        default=True,
        help="Run containers in detached mode (default: True)",
    )
    launch_parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable dev mode: mount local src directory to container (single container only)",
    )
    launch_parser.add_argument(
        "--vnc",
        action="store_true",
        help="[Legacy alias for --viewer] Enable web-scrcpy viewer",
    )
    launch_parser.add_argument(
        "--viewer",
        action="store_true",
        help="Enable web-scrcpy viewer (accessible via viewer port)",
    )
    launch_parser.add_argument(
        "--dry-run",
        "--dry_run",
        dest="dry_run",
        action="store_true",
        help="Print docker commands without executing them",
    )
    launch_parser.add_argument(
        "--env-file",
        "--env_file",
        dest="env_file",
        type=str,
        help="Path to .env file to mount in container (required if .env not found in current directory)",
    )
    launch_parser.add_argument(
        "--mount-src",
        "--mount_src",
        dest="mount_src",
        action="store_true",
        help="Mount local src directory to container",
    )
    launch_parser.add_argument(
        "--launch-interval",
        "--launch_interval",
        dest="launch_interval",
        type=int,
        default=10,
        help="Seconds to wait between launching each container (default: 10)",
    )
    launch_parser.add_argument(
        "--http-proxy",
        "--http_proxy",
        dest="http_proxy",
        type=str,
        default=None,
        help=(
            "HTTP(S) proxy URL forwarded to the container (Python) and the "
            "Android emulator (system-wide). Example: http://proxy.host:8888. "
            "10.0.2.2/127.0.0.1/localhost are always excluded."
        ),
    )

    # Destroy subcommand
    destroy_parser = env_subparsers.add_parser(
        "rm",
        help="Destroy Docker container(s)",
    )
    destroy_parser.add_argument(
        "container_names",
        nargs="*",
        help="Container names to destroy (omit for all mobile_world containers)",
    )
    destroy_parser.add_argument(
        "--all",
        action="store_true",
        help="Destroy all containers with mobile_world prefix",
    )
    _add_common_options(destroy_parser, image=True, prefix=True)

    # List subcommand
    list_parser = env_subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="List running MobileWorld containers",
    )
    list_parser.add_argument(
        "--all",
        action="store_true",
        help="Show all containers (including stopped)",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output in JSON format",
    )
    _add_common_options(list_parser, image=True, prefix=True)
    # Info subcommand
    info_parser = env_subparsers.add_parser(
        "info",
        help="Get detailed info about a container",
    )
    info_parser.add_argument(
        "container_name",
        help="Container name to inspect",
    )
    info_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output in JSON format",
    )
    _add_common_options(info_parser, prefix=True)

    # Restart subcommand
    restart_parser = env_subparsers.add_parser(
        "restart",
        help="Restart the MobileWorld server in a container",
    )
    restart_parser.add_argument(
        "container_name",
        nargs="?",
        default=None,
        help="Container name to restart (omit to restart all matching containers)",
    )
    restart_parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Enter interactive mode (only works with single container)",
    )
    _add_common_options(restart_parser, image=True, prefix=True)

    # Exec subcommand
    exec_parser = env_subparsers.add_parser(
        "exec",
        help="Open a bash shell in a container",
    )
    exec_parser.add_argument(
        "container_name",
        help="Container name to attach to",
    )
    exec_parser.add_argument(
        "--command",
        "-c",
        dest="exec_command",
        default="/bin/bash",
        help="Command to execute (default: /bin/bash)",
    )
    _add_common_options(exec_parser, prefix=True)

    # Check subcommand
    env_subparsers.add_parser(
        "check",
        help="Check prerequisites for running MobileWorld (Docker, KVM)",
    )


def _wait_for_container_ready_with_progress(
    backend_port: int, timeout: int = 120, start_time: float | None = None
) -> bool:
    """Wait for container to be ready with progress display."""
    start_time = start_time or time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[cyan]Waiting for container on port {backend_port}...[/cyan]",
            total=timeout,
        )

        while time.time() - start_time < timeout:
            elapsed = time.time() - start_time
            progress.update(task, completed=elapsed)

            if wait_for_container_ready(backend_port, timeout=1, poll_interval=1):
                progress.update(
                    task,
                    description=f"[green]✓ Ready![/green] (took {elapsed:.1f}s)",
                    completed=timeout,
                )
                return True

        progress.update(
            task,
            description="[red]✗ Timeout waiting for container[/red]",
            completed=timeout,
        )

    return False


def _launch_containers(args: argparse.Namespace) -> None:
    """Launch Docker containers."""
    count = args.count

    # Dev mode only allows single container
    if args.dev and count > 1:
        console.print(
            Panel(
                "[red]Dev mode only supports launching a single container.[/red]\n"
                "[yellow]Please use --count 1 or omit --count when using --dev[/yellow]",
                title="[red]✗ Error[/red]",
                border_style="red",
            )
        )
        sys.exit(1)

    port_sets = find_available_ports(
        args.backend_start_port, args.viewer_start_port, args.adb_start_port, count
    )

    if len(port_sets) < count:
        console.print(
            Panel(
                f"[yellow]Could only find {len(port_sets)} available port sets out of {count} requested[/yellow]",
                title="[yellow]⚠ Port Warning[/yellow]",
                border_style="yellow",
            )
        )

    # Get current working directory
    current_path = Path.cwd()

    # Handle dev mode - find project root
    dev_src_path = None
    if args.dev or args.mount_src:
        project_root = None
        for parent in [current_path] + list(current_path.parents):
            if (parent / "pyproject.toml").exists():
                project_root = parent
                break

        if project_root:
            dev_src_path = project_root / "src"
            if not dev_src_path.exists():
                console.print(
                    Panel(
                        f"[yellow]src directory not found at {dev_src_path}[/yellow]",
                        title="[yellow]⚠ Warning[/yellow]",
                        border_style="yellow",
                    )
                )
                dev_src_path = None
            else:
                console.print(
                    Panel(
                        f"[green]Dev mode enabled[/green]\n[cyan]Mounting:[/cyan] {dev_src_path} → /app/service/src",
                        title="[green]🔧 Dev Mode[/green]",
                        border_style="green",
                    )
                )
        else:
            console.print(
                Panel(
                    "[yellow]Could not find project root (pyproject.toml). Dev mode disabled.[/yellow]",
                    title="[yellow]⚠ Warning[/yellow]",
                    border_style="yellow",
                )
            )

    # Handle .env file mounting
    env_file_path = None
    default_env_path = current_path / ".env"

    if default_env_path.exists():
        env_file_path = default_env_path
        console.print(
            Panel(
                f"[green]Found .env file[/green]\n[cyan]Mounting:[/cyan] {env_file_path} → /app/service/.env",
                title="[green]📄 Environment File[/green]",
                border_style="green",
            )
        )
    elif args.env_file:
        env_file_path = Path(args.env_file)
        if not env_file_path.exists():
            console.print(
                Panel(
                    f"[red]Environment file not found: {env_file_path}[/red]",
                    title="[red]✗ Error[/red]",
                    border_style="red",
                )
            )
            sys.exit(1)
        if not env_file_path.is_file():
            console.print(
                Panel(
                    f"[red]Path is not a file: {env_file_path}[/red]",
                    title="[red]✗ Error[/red]",
                    border_style="red",
                )
            )
            sys.exit(1)
        console.print(
            Panel(
                f"[green]Using specified .env file[/green]\n[cyan]Mounting:[/cyan] {env_file_path} → /app/service/.env",
                title="[green]📄 Environment File[/green]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                "[red]No .env file found in current directory and --env-file not specified[/red]\n"
                "[yellow]Please provide --env-file argument with path to .env file[/yellow]",
                title="[red]✗ Error[/red]",
                border_style="red",
            )
        )
        sys.exit(1)

    console.print(
        Panel(
            f"[cyan]Launching {count} container(s)[/cyan]\n[dim]Image:[/dim] {args.image}",
            title="[bold cyan]🚀 Launching Containers[/bold cyan]",
            border_style="cyan",
        )
    )

    start_index = find_next_container_index(args.name_prefix, args.dev)

    # Pre-compute container configurations
    container_configs = []
    for i, (backend, viewer, adb) in enumerate(port_sets):
        config = ContainerConfig(
            name=f"{args.name_prefix}_{start_index + i}{'_dev' if args.dev else ''}",
            backend_port=backend,
            viewer_port=viewer,
            adb_port=adb,
            image=args.image,
            dev_mode=args.dev,
            enable_vnc=args.vnc or args.dev,
            enable_viewer=getattr(args, "viewer", False) or args.vnc or args.dev,
            env_file_path=env_file_path,
            dev_src_path=dev_src_path,
            http_proxy=args.http_proxy,
        )
        container_configs.append(config)

    # Display planned containers
    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Backend", justify="right", style="yellow")
    table.add_column("Viewer", justify="right", style="yellow")
    table.add_column("ADB", justify="right", style="yellow")

    for idx, config in enumerate(container_configs, 1):
        table.add_row(
            f"{idx}/{len(container_configs)}",
            config.name,
            str(config.backend_port),
            str(config.viewer_port),
            str(config.adb_port),
        )

    console.print(
        Panel(
            table,
            title="[bold cyan]Planned Containers[/bold cyan]",
            border_style="cyan",
        )
    )

    if args.dry_run:
        cmd_table = Table(show_header=True, header_style="bold yellow", box=box.ROUNDED)
        cmd_table.add_column("Container", style="cyan", no_wrap=True)
        cmd_table.add_column("Command", style="dim")

        for config in container_configs:
            envs: dict[str, str] = {}
            if config.enable_vnc or config.dev_mode:
                envs["ENABLE_VNC"] = "true"
            if config.enable_viewer:
                envs["ENABLE_VIEWER"] = "true"
            if config.http_proxy:
                envs["http_proxy"] = config.http_proxy
                envs["https_proxy"] = config.http_proxy
                envs["HTTP_PROXY"] = config.http_proxy
                envs["HTTPS_PROXY"] = config.http_proxy
                # NO_PROXY must be passed at `docker run -e` time so it's
                # visible to every fresh process in the container —
                # `docker exec` shells, the HEALTHCHECK, etc. The entrypoint's
                # `export NO_PROXY=...` only reaches its own children.
                envs["no_proxy"] = "10.0.2.2,127.0.0.1,localhost,::1"
                envs["NO_PROXY"] = "10.0.2.2,127.0.0.1,localhost,::1"

            volumes: list[tuple[str, str]] = []
            if config.dev_src_path:
                volumes.append((str(config.dev_src_path), "/app/service/src"))
            if config.env_file_path:
                volumes.append((str(config.env_file_path.resolve()), "/app/service/.env"))

            cmd = build_run_command(
                name=config.name,
                image=config.image,
                port_mappings=[
                    (config.backend_port, 6800),
                    (config.viewer_port, 7860),
                ],
                env_vars=envs,
                volumes=volumes,
                detach=args.detach,
                privileged=True,
                remove=True,
            )
            cmd_table.add_row(config.name, " ".join(cmd))

        console.print(
            Panel(
                cmd_table,
                title="[yellow]🔍 Docker Commands[/yellow]",
                border_style="yellow",
            )
        )
        console.print(
            Panel(
                f"[green]✓ Dry-run complete[/green]\n[dim]{len(container_configs)} docker command(s) prepared[/dim]",
                title="[green]✓ Dry-run Complete[/green]",
                border_style="green",
            )
        )
        return

    # Launch containers
    launch_interval = args.launch_interval
    launched = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for idx, config in enumerate(container_configs):
            task = progress.add_task(
                f"[cyan]Launching {config.name}...[/cyan]",
                total=None,
            )

            result = launch_container(config, wait_ready=False)

            if result.success:
                progress.update(
                    task,
                    description=f"[green]✓ {config.name} launched[/green]",
                )
                launched.append(
                    {
                        "name": config.name,
                        "backend_port": config.backend_port,
                        "viewer_port": config.viewer_port,
                        "adb_port": config.adb_port,
                        "ready": False,
                    }
                )
            else:
                progress.update(
                    task,
                    description=f"[red]✗ {config.name} failed[/red]",
                )
                console.print(
                    Panel(
                        f"[red]Failed to launch container '{config.name}'[/red]",
                        title="[red]✗ Launch Failed[/red]",
                        border_style="red",
                    )
                )

            if launch_interval > 0 and idx < len(container_configs) - 1:
                wait_task = progress.add_task(
                    f"[yellow]Waiting {launch_interval}s before next launch...[/yellow]",
                    total=launch_interval,
                )
                for _ in range(launch_interval):
                    time.sleep(1)
                    progress.advance(wait_task)
                progress.update(
                    wait_task,
                    description="[dim]✓ Wait complete[/dim]",
                )

    # Wait for all containers to become ready
    if launched:
        console.print()
        console.print(
            Panel(
                f"[cyan]Waiting for {len(launched)} container(s) to become ready...[/cyan]",
                title="[bold cyan]⏳ Waiting for Readiness[/bold cyan]",
                border_style="cyan",
            )
        )
        start_time = time.time()
        for container in launched:
            console.print(f"\n[dim]Checking container '{container['name']}'...[/dim]")
            if _wait_for_container_ready_with_progress(
                container["backend_port"], timeout=600, start_time=start_time
            ):
                container["ready"] = True
                console.print(f"[green]✓ Container '{container['name']}' is ready[/green]")
            else:
                console.print(
                    Panel(
                        f"[yellow]Container '{container['name']}' did not become ready in time[/yellow]",
                        title="[yellow]⚠ Warning[/yellow]",
                        border_style="yellow",
                    )
                )

    ready_count = sum(1 for c in launched if c.get("ready", False))
    console.print()
    console.print(
        Panel(
            f"[green]✓ Successfully launched {len(launched)} container(s)[/green]\n"
            f"[cyan]{ready_count} ready, {len(launched) - ready_count} pending[/cyan]",
            title="[bold green]✓ Launch Complete[/bold green]",
            border_style="green",
        )
    )

    # Print summary table
    console.print()
    table = Table(title="Launched Containers", show_header=True, header_style="bold magenta")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Backend", justify="right", style="yellow")
    if not args.dev:
        table.add_column("Viewer", justify="right", style="yellow")
    table.add_column("ADB", justify="right", style="yellow")
    table.add_column("Status", justify="center")

    for container in launched:
        status = (
            "[green]✓ Ready[/green]"
            if container.get("ready", False)
            else "[yellow]⚠ Not Ready[/yellow]"
        )
        row_data = [
            container["name"],
            str(container["backend_port"]),
        ]
        if not args.dev:
            row_data.append(str(container["viewer_port"]))
        row_data.append(str(container["adb_port"]))
        row_data.append(status)
        table.add_row(*row_data)

    console.print(table)


def _destroy_containers(args: argparse.Namespace) -> None:
    """Destroy Docker containers."""
    container_names = None
    if not args.all and args.container_names:
        container_names = args.container_names

    destroyed, failed = remove_containers(
        container_names=container_names,
        image_filter=args.image,
        name_prefix=args.name_prefix,
    )

    if not destroyed and not failed:
        console.print(
            Panel(
                "[yellow]No containers to destroy[/yellow]",
                title="[yellow]ℹ Info[/yellow]",
                border_style="yellow",
            )
        )
        return

    if destroyed:
        console.print(
            Panel(
                f"[green]✓ Successfully destroyed {len(destroyed)} container(s)[/green]",
                title="[green]✓ Destruction Complete[/green]",
                border_style="green",
            )
        )
    if failed:
        console.print(
            Panel(
                f"[red]✗ Failed to destroy {len(failed)} container(s)[/red]\n"
                + "\n".join(f"[dim]- {c}[/dim]" for c in failed),
                title="[red]✗ Errors[/red]",
                border_style="red",
            )
        )


def _list_containers(args: argparse.Namespace) -> None:
    """List MobileWorld containers."""
    containers = list_containers(
        image_filter=args.image,
        name_prefix=args.name_prefix,
        include_all=args.all,
    )

    if not containers:
        console.print(
            Panel(
                "[yellow]No MobileWorld containers found[/yellow]",
                title="[yellow]ℹ Info[/yellow]",
                border_style="yellow",
            )
        )
        return

    if args.json_output:
        output = [
            {
                "name": c.name,
                "status": c.status,
                "running": c.running,
                "backend_port": c.backend_port,
                "viewer_port": c.viewer_port,
            }
            for c in containers
        ]
        sys.stdout.write(json.dumps(output, indent=2) + "\n")
    else:
        console.print(
            Panel(
                f"[cyan]Found {len(containers)} container(s)[/cyan]",
                title="[bold cyan]📋 Container List[/bold cyan]",
                border_style="cyan",
            )
        )
        console.print()

        table = Table(
            title="MobileWorld Containers",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Status", style="green")
        table.add_column("Backend", style="yellow", justify="right")
        table.add_column("Viewer", style="yellow", justify="right")
        table.add_column("ADB", style="yellow", justify="right")

        for c in containers:
            backend = f"http://0.0.0.0:{c.backend_port}" if c.backend_port else "N/A"
            viewer = f"http://0.0.0.0:{c.viewer_port}" if c.viewer_port else "N/A"
            adb = f"localhost:{c.adb_port}" if c.adb_port else "N/A"
            table.add_row(c.name, c.status or "N/A", backend, viewer, adb)

        console.print(table)


def _info_container(args: argparse.Namespace) -> None:
    """Get detailed info about a container."""
    container_name = resolve_container_name(args.container_name, args.name_prefix)
    info = get_container_info(container_name)

    if not info:
        console.print(
            Panel(
                f"[red]Container '{container_name}' not found[/red]",
                title="[red]✗ Error[/red]",
                border_style="red",
            )
        )
        return

    if args.json_output:
        output = {
            "name": info.name,
            "status": info.status,
            "running": info.running,
            "started_at": info.started_at,
            "image": info.image,
            "backend_port": info.backend_port,
            "viewer_port": info.viewer_port,
        }
        sys.stdout.write(json.dumps(output, indent=2) + "\n")
    else:
        console.print(
            Panel(
                "[cyan]Container Information[/cyan]",
                title=f"[bold cyan]ℹ️  {info.name}[/bold cyan]",
                border_style="cyan",
            )
        )
        console.print()

        info_table = Table(
            show_header=True,
            header_style="bold cyan",
            box=box.ROUNDED,
        )
        info_table.add_column("Property", style="yellow", no_wrap=True)
        info_table.add_column("Value", style="green")

        status_style = "[green]" if info.running else "[red]"
        info_table.add_row("Status", f"{status_style}{info.status}[/{status_style[1:]}")
        info_table.add_row("Running", f"{status_style}{info.running}[/{status_style[1:]}")
        info_table.add_row("Started At", info.started_at or "N/A")
        info_table.add_row("Image", info.image or "N/A")

        console.print(info_table)

        if info.backend_port or info.viewer_port or info.adb_port:
            console.print()
            port_table = Table(
                title="Port Mappings",
                show_header=True,
                header_style="bold magenta",
                box=box.ROUNDED,
            )
            port_table.add_column("Service", style="cyan")
            port_table.add_column("Port", style="yellow", justify="right")

            if info.backend_port:
                port_table.add_row("Backend (6800)", str(info.backend_port))
            if info.viewer_port:
                port_table.add_row("Viewer (7860)", str(info.viewer_port))
            if info.adb_port:
                port_table.add_row("ADB (5556)", str(info.adb_port))

            console.print(port_table)


def _restart_single_container(container_name: str, interactive: bool = False) -> bool:
    """Restart the MobileWorld server in a single container."""
    console.print(
        Panel(
            f"[cyan]Killing MobileWorld server in container '{container_name}'...[/cyan]",
            title="[bold cyan]🔄 Killing Server[/bold cyan]",
            border_style="cyan",
        )
    )
    if not kill_server_in_container(container_name):
        return False

    console.print(
        Panel(
            f"[cyan]Restarting MobileWorld server in container '{container_name}'...[/cyan]",
            title="[bold cyan]🔄 Restarting Server[/bold cyan]",
            border_style="cyan",
        )
    )

    if interactive:
        console.print(
            Panel(
                "[cyan]Entering interactive mode...[/cyan]",
                title="[bold cyan]💻 Interactive Mode[/bold cyan]",
                border_style="cyan",
            )
        )
        docker_exec_replace(
            container_name,
            "cd /app/service && uv run mobile-world server --port 6800 --enable-mcp",
            interactive=True,
        )
        return True

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Restarting server...[/cyan]", total=None)

        if restart_server_in_container(container_name, detach=True, enable_mcp=True):
            progress.update(task, description="[green]✓ Server restarted[/green]")
            console.print(
                Panel(
                    "[green]✓ Server restart complete[/green]",
                    title="[bold green]✓ Restart Complete[/bold green]",
                    border_style="green",
                )
            )
            return True
        else:
            progress.update(task, description="[red]✗ Failed to restart server[/red]")
            console.print(
                Panel(
                    "[red]✗ Failed to start server[/red]",
                    title="[red]✗ Error[/red]",
                    border_style="red",
                )
            )
            return False


def _restart_server(args: argparse.Namespace) -> None:
    """Restart the MobileWorld server in container(s)."""
    if args.container_name:
        container_name = resolve_container_name(args.container_name, args.name_prefix)
        success = _restart_single_container(container_name, interactive=args.interactive)
        if not success:
            sys.exit(1)
    else:
        if args.interactive:
            console.print(
                Panel(
                    "[red]Interactive mode (-i) is not supported when restarting multiple containers[/red]",
                    title="[red]✗ Error[/red]",
                    border_style="red",
                )
            )
            sys.exit(1)

        containers = list_containers(
            image_filter=args.image,
            name_prefix=args.name_prefix,
            include_all=False,
        )
        running_containers = [c for c in containers if c.running]

        if not running_containers:
            console.print(
                Panel(
                    f"[yellow]No running containers found matching prefix '{args.name_prefix}'[/yellow]",
                    title="[yellow]ℹ Info[/yellow]",
                    border_style="yellow",
                )
            )
            return

        console.print(
            Panel(
                f"[cyan]Restarting {len(running_containers)} container(s)...[/cyan]",
                title="[bold cyan]🔄 Restarting Servers[/bold cyan]",
                border_style="cyan",
            )
        )

        success_count = 0
        for c in running_containers:
            console.print()
            if _restart_single_container(c.name, interactive=False):
                success_count += 1

        console.print()
        console.print(
            Panel(
                f"[green]✓ Restarted {success_count}/{len(running_containers)} container(s)[/green]",
                title="[bold green]✓ Restart Complete[/bold green]",
                border_style="green",
            )
        )


def _exec_container(args: argparse.Namespace) -> None:
    """Execute a command or open bash in a container."""
    container_name = resolve_container_name(args.container_name, args.name_prefix)
    command = args.exec_command

    console.print(
        Panel(
            f"[cyan]Executing:[/cyan] [bold]{command}[/bold]\n[dim]Container:[/dim] {container_name}",
            title="[bold cyan]💻 Executing Command[/bold cyan]",
            border_style="cyan",
        )
    )

    docker_exec_replace(container_name, command, interactive=True)


def _check_env_file() -> tuple[bool, str, str | None]:
    """Check if .env file exists and has valid configuration.

    Returns:
        Tuple of (passed, message, details)
    """

    env_path = Path.cwd() / ".env"

    if not env_path.exists():
        return (
            False,
            ".env file not found in current directory",
            "Create a .env file with required environment variables.\n"
            "See .env.example for reference.",
        )

    # Load .env file using dotenv
    try:
        env_vars = dotenv_values(env_path)
    except Exception as e:
        return (
            False,
            f"Failed to read .env file: {e}",
            None,
        )

    issues = []
    warnings = []

    # Define placeholder values to check against
    placeholders = {
        "API_KEY": "your_api_key_for_agent_model",
        "DASHSCOPE_API_KEY": "dashscope_api_key_for_mcp",
        "MODELSCOPE_API_KEY": "modelscope_api_key_for_mcp",
        "USER_AGENT_API_KEY": "your_user_agent_llm_api_key",
        "USER_AGENT_BASE_URL": "your_user_agent_base_url",
    }

    def is_valid(key: str) -> bool:
        """Check if env var exists and is not a placeholder."""
        value = env_vars.get(key)
        if not value:
            return False
        if value == placeholders.get(key):
            return False
        return True

    # 1. Check API_KEY (required for all tasks)
    if not is_valid("API_KEY"):
        if env_vars.get("API_KEY") == placeholders["API_KEY"]:
            issues.append("API_KEY is still set to placeholder value")
        else:
            issues.append("API_KEY is missing (required for all tasks)")

    # 2. Check MCP keys (optional - for MCP tasks)
    mcp_keys_missing = []
    mcp_keys_placeholder = []
    for key in ["DASHSCOPE_API_KEY", "MODELSCOPE_API_KEY"]:
        if env_vars.get(key) == placeholders.get(key):
            mcp_keys_placeholder.append(key)
        elif not env_vars.get(key):
            mcp_keys_missing.append(key)

    if mcp_keys_placeholder:
        warnings.append(f"{', '.join(mcp_keys_placeholder)}: placeholder value (required for MCP tasks)")
    if mcp_keys_missing:
        warnings.append(f"{', '.join(mcp_keys_missing)}: not set (required for MCP tasks)")

    # 3. Check USER_AGENT_* keys (optional - for agent-user interaction tasks)
    user_agent_keys = ["USER_AGENT_API_KEY", "USER_AGENT_BASE_URL", "USER_AGENT_MODEL"]
    user_agent_missing = []
    user_agent_placeholder = []
    for key in user_agent_keys:
        if env_vars.get(key) == placeholders.get(key):
            user_agent_placeholder.append(key)
        elif not env_vars.get(key):
            user_agent_missing.append(key)

    if user_agent_placeholder:
        warnings.append(
            f"{', '.join(user_agent_placeholder)}: placeholder value (required for agent-user interaction tasks)"
        )
    if user_agent_missing:
        warnings.append(
            f"{', '.join(user_agent_missing)}: not set (required for agent-user interaction tasks)"
        )

    # Build result
    if issues:
        details = "\n".join(f"✗ {issue}" for issue in issues)
        if warnings:
            details += "\n\n[yellow]Warnings:[/yellow]\n" + "\n".join(f"⚠ {w}" for w in warnings)
        return (False, "Required environment variables not configured", details)

    if warnings:
        details = "[yellow]Optional variables not configured:[/yellow]\n"
        details += "\n".join(f"⚠ {w}" for w in warnings)
        return (True, ".env configured (some optional vars missing)", details)

    return (True, ".env file configured correctly", None)


def _check_prerequisites(args: argparse.Namespace) -> None:
    """Check prerequisites for running MobileWorld."""
    _ = args  # unused

    console.print(
        Panel(
            "[cyan]Checking prerequisites for MobileWorld...[/cyan]",
            title="[bold cyan]🔍 Prerequisite Check[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()

    results = check_prerequisites()

    # Add .env file check
    env_passed, env_message, env_details = _check_env_file()
    from mobile_world.runtime.utils.models import PrerequisiteCheckResult

    env_check = PrerequisiteCheckResult(
        name=".env Configuration",
        passed=env_passed,
        message=env_message,
        details=env_details,
    )
    results.checks.append(env_check)

    table = Table(
        show_header=True,
        header_style="bold magenta",
        box=box.ROUNDED,
    )
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Message", style="dim")

    for check in results.checks:
        status = "[green]✓ PASS[/green]" if check.passed else "[red]✗ FAIL[/red]"
        table.add_row(check.name, status, check.message)

    console.print(table)

    # Print details for failed checks
    failed_checks = [c for c in results.checks if not c.passed]
    if failed_checks:
        console.print()
        console.print(
            Panel(
                "[yellow]Details for failed checks:[/yellow]",
                title="[yellow]⚠ Fix Required[/yellow]",
                border_style="yellow",
            )
        )
        for check in failed_checks:
            if check.details:
                console.print(f"\n[bold red]{check.name}[/bold red]")
                console.print(f"[dim]{check.details}[/dim]")

    console.print()
    if results.all_passed:
        console.print(
            Panel(
                f"[green]✓ All {results.passed_count} checks passed![/green]\n"
                "[cyan]Environment is ready for MobileWorld.[/cyan]",
                title="[bold green]✓ Ready[/bold green]",
                border_style="green",
            )
        )

        # Check Docker image status
        console.print()
        console.print(
            Panel(
                f"[cyan]Checking Docker image status...[/cyan]\n[dim]{DEFAULT_IMAGE}[/dim]",
                title="[bold cyan]🐳 Image Check[/bold cyan]",
                border_style="cyan",
            )
        )

        image_status = check_image_status(DEFAULT_IMAGE)

        if not image_status.exists_locally:
            console.print(
                Panel(
                    f"[yellow]Docker image not found locally[/yellow]\n[dim]{DEFAULT_IMAGE}[/dim]",
                    title="[yellow]⚠ Image Missing[/yellow]",
                    border_style="yellow",
                )
            )
            _offer_image_pull(DEFAULT_IMAGE)
        elif image_status.needs_update:
            console.print(
                Panel(
                    "[yellow]A newer version of the Docker image is available[/yellow]\n"
                    f"[dim]Local:  {image_status.local_digest[:12] if image_status.local_digest else 'unknown'}...[/dim]\n"
                    f"[dim]Remote: {image_status.remote_digest[:12] if image_status.remote_digest else 'unknown'}...[/dim]",
                    title="[yellow]⚠ Update Available[/yellow]",
                    border_style="yellow",
                )
            )
            _offer_image_pull(DEFAULT_IMAGE)
        else:
            console.print(
                Panel(
                    f"[green]✓ Docker image is up-to-date[/green]\n[dim]{DEFAULT_IMAGE}[/dim]",
                    title="[bold green]✓ Image Ready[/bold green]",
                    border_style="green",
                )
            )
    else:
        console.print(
            Panel(
                f"[red]✗ {results.failed_count} check(s) failed[/red]\n"
                "[yellow]Please fix the issues above before running `mw eval`.[/yellow]",
                title="[bold red]✗ Not Ready[/bold red]",
                border_style="red",
            )
        )
        sys.exit(1)


def _offer_image_pull(image: str) -> None:
    """Offer to pull a Docker image interactively.

    Args:
        image: Docker image name to pull
    """
    console.print()
    try:
        response = console.input("[cyan]Would you like to pull the image now? [y/N]: [/cyan]")
        if response.lower() in ("y", "yes"):
            console.print()
            console.print(
                Panel(
                    f"[cyan]Pulling Docker image...[/cyan]\n[dim]{image}[/dim]",
                    title="[bold cyan]⬇️  Pulling Image[/bold cyan]",
                    border_style="cyan",
                )
            )
            console.print()
            success, message = pull_image(image)
            console.print()
            if success:
                console.print(
                    Panel(
                        f"[green]✓ {message}[/green]",
                        title="[bold green]✓ Pull Complete[/bold green]",
                        border_style="green",
                    )
                )
            else:
                console.print(
                    Panel(
                        f"[red]✗ {message}[/red]",
                        title="[bold red]✗ Pull Failed[/bold red]",
                        border_style="red",
                    )
                )
        else:
            console.print(
                Panel(
                    "[dim]Skipping image pull. Run 'docker pull "
                    f"{image}' manually when ready.[/dim]",
                    title="[dim]ℹ Skipped[/dim]",
                    border_style="dim",
                )
            )
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")


async def execute(args: argparse.Namespace) -> None:
    """Execute the env command."""
    action_map: dict[str, Callable] = {
        "run": _launch_containers,
        "rm": _destroy_containers,
        "list": _list_containers,
        "ls": _list_containers,
        "info": _info_container,
        "restart": _restart_server,
        "exec": _exec_container,
        "check": _check_prerequisites,
    }

    action = action_map.get(args.env_action)
    if action:
        action(args)
