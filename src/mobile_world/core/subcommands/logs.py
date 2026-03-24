"""Logs subcommand for MobileWorld CLI - Work with trajectory logs."""

import argparse
import os
import subprocess
import sys


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configure the logs subcommand parser."""
    logs_parser = subparsers.add_parser(
        "logs",
        help="Work with trajectory logs (view/analyze/export)",
    )

    logs_subparsers = logs_parser.add_subparsers(
        dest="logs_command",
        help="Logs commands",
    )

    # logs view - Interactive log viewing
    view_parser = logs_subparsers.add_parser(
        "view",
        help="Launch interactive log viewer",
    )
    view_parser.add_argument(
        "--log-dir",
        "--log_dir",
        dest="log_dir",
        required=True,
        help="Trajectory directory or parent directory containing trajectory dirs (e.g., traj_logs/logs_20251029_4 or traj_logs/)",
    )
    view_parser.add_argument(
        "--port",
        type=int,
        default=8760,
        help="Port for the viewer (default: 8760)",
    )
    view_parser.add_argument(
        "--base",
        type=str,
        default="/",
        help="Base path for deployment (default: /). Use '/site/' if deploying at /site/",
    )

    # logs results - Print results table
    results_parser = logs_subparsers.add_parser(
        "results",
        help="Print results table for log directories",
    )
    results_parser.add_argument(
        "log_dirs",
        nargs="+",
        metavar="LOG_DIR",
        help="One or more log root directories to analyze",
    )

    # logs export - Export static site
    export_parser = logs_subparsers.add_parser(
        "export",
        help="Export logs as a static HTML site",
    )
    export_parser.add_argument(
        "--log-dir",
        "--log_dir",
        dest="log_dir",
        required=True,
        help="Root directory for log files",
    )
    export_parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output directory for the static site",
    )


def print_results_table(log_roots: list[str]) -> None:
    """Print results for multiple log roots as a table."""
    from rich.console import Console
    from rich.table import Table

    from mobile_world.core.log_viewer.utils import calculate_task_stats, read_log_metadata

    console = Console()

    table = Table(title="Log Results Summary", show_header=True, header_style="bold cyan")
    table.add_column("Log Root", style="dim", no_wrap=True)
    table.add_column("Suite", style="magenta")
    table.add_column("Total", justify="right")
    table.add_column("Finished", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("SR%", justify="right")
    table.add_column("Std SR%", justify="right")
    table.add_column("MCP SR%", justify="right")
    table.add_column("UI SR%", justify="right")
    table.add_column("UIQ", justify="right")
    table.add_column("Avg Steps", justify="right")
    table.add_column("Avg Queries", justify="right")
    table.add_column("Avg MCP", justify="right")

    for log_root in log_roots:
        if not os.path.exists(log_root):
            console.print(f"[yellow]Warning: {log_root} does not exist, skipping.[/yellow]")
            continue

        metadata = read_log_metadata(log_root)
        suite_family = metadata.get("suite_family", "mobile_world")
        stats = calculate_task_stats(log_root, suite_family=suite_family)
        # Use basename for display, but show full path if duplicates exist
        display_name = os.path.basename(log_root.rstrip("/"))

        table.add_row(
            display_name,
            suite_family.replace("_", " ").title(),
            str(stats["total"]),
            str(stats["finished"]),
            str(stats["success"]),
            f"{stats['success_rate']:.1f}",
            f"{stats['standard_success_rate']:.1f}",
            f"{stats['mcp_success_rate']:.1f}",
            f"{stats['user_interaction_success_rate']:.1f}",
            f"{stats['uiq']:.3f}",
            f"{stats['avg_steps']:.1f}",
            f"{stats['avg_queries']:.2f}",
            f"{stats['avg_mcp_calls']:.2f}",
        )

    console.print(table)


async def execute(args: argparse.Namespace) -> None:
    """Execute the logs command."""
    if args.logs_command == "view":
        await _execute_view(args)
    elif args.logs_command == "results":
        _execute_results(args)
    elif args.logs_command == "export":
        _execute_export(args)
    else:
        print("❌ Error: Please specify a subcommand (view, results, export)")
        print("Run 'mobile-world logs --help' for usage information.")
        sys.exit(1)


async def _execute_view(args: argparse.Namespace) -> None:
    """Execute the logs view command."""
    try:
        print("🚀 Starting MobileWorld Log Viewer...")
        print(f"📂 Log Root: {args.log_dir}")
        print(f"🌐 Opening web interface on port {args.port}...")

        # Build command arguments - run as module
        cmd = [
            sys.executable,
            "-m",
            "mobile_world.core.log_viewer",
            args.log_dir,
            str(args.port),
            args.base,
        ]

        # Run the script as a subprocess
        # This will block until the server is stopped (Ctrl+C)
        subprocess.run(cmd, check=True)

    except KeyboardInterrupt:
        print("\n👋 Shutting down log viewer...")
        sys.exit(0)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error starting log viewer: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error starting log viewer: {e}")
        sys.exit(1)


def _execute_results(args: argparse.Namespace) -> None:
    """Execute the logs results command."""
    print_results_table(args.log_dirs)


def _execute_export(args: argparse.Namespace) -> None:
    """Execute the logs export command."""
    from mobile_world.core.log_viewer.static_export import export_static_site

    if not os.path.exists(args.log_dir):
        print(f"❌ Error: Log directory does not exist: {args.log_dir}")
        sys.exit(1)

    export_static_site(args.log_dir, args.output)
