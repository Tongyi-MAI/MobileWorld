"""Eval subcommand for MobileWorld CLI - Run benchmark evaluation suite."""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..runner import run_agent_with_evaluation


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add common arguments shared between eval and test commands."""
    parser.add_argument(
        "--agent-type",
        "--agent_type",
        required=True,
        dest="agent_type",
        help="Type of agent to use (registered name or path to Python file containing agent class)",
    )
    parser.add_argument("--model-name", "--model_name", dest="model_name", help="Model name to use")
    parser.add_argument(
        "--llm-base-url",
        "--llm_base_url",
        dest="llm_base_url",
        help="LLM service base URL",
    )
    parser.add_argument(
        "--api-key",
        "--api_key",
        dest="api_key",
        help="API key for LLM service",
    )
    parser.add_argument(
        "--log-file-root",
        "--log_file_root",
        dest="log_file_root",
        help="Root directory for log files",
    )
    parser.add_argument(
        "--max-round",
        "--max_round",
        "--max-step",
        "--max_step",
        dest="max_round",
        type=int,
        help="Maximum number of steps (-1 for unlimited)",
    )
    parser.add_argument(
        "--aw-host", "--aw_host", dest="aw_host", help="Android World server host", default=None
    )
    parser.add_argument("--timeout", type=int, help="Task timeout in seconds")
    parser.add_argument("--output", dest="output", help="Output directory for results")

    # Executor settings for planner-executor agents
    parser.add_argument(
        "--executor-llm-base-url",
        "--executor_llm_base_url",
        dest="executor_llm_base_url",
        help="Executor LLM service base URL",
    )
    parser.add_argument(
        "--executor-model-name",
        "--executor_model_name",
        dest="executor_model_name",
        help="Executor model name",
    )
    parser.add_argument(
        "--executor-agent-class",
        "--executor_agent_class",
        dest="executor_agent_class",
        help="Executor agent class name",
    )

    # Device configuration
    parser.add_argument(
        "--device",
        dest="device",
        default=None,
        help="Android device ID (default: get via adb devices)",
    )
    parser.add_argument(
        "--step-wait-time",
        "--step_wait_time",
        dest="step_wait_time",
        type=float,
        default=1.0,
        help="Wait time in seconds after each step (default: 1.0)",
    )
    parser.add_argument(
        "--suite-family",
        "--suite_family",
        dest="suite_family",
        choices=["mobile_world", "android_world"],
        default="mobile_world",
        help="Suite family to use (default: mobile_world)",
    )
    parser.add_argument(
        "--env-name-prefix",
        "--env_name_prefix",
        "--env-prefix",
        "--env_prefix",
        dest="env_name_prefix",
        default="mobile_world_env",
        help="Name prefix for containers (default: mobile_world_env)",
    )
    parser.add_argument(
        "--env-image",
        "--env_image",
        dest="env_image",
        default="mobile_world",
        help="Image name for containers (default: mobile_world)",
    )
    parser.add_argument(
        "--enable-mcp",
        "--enable_mcp",
        dest="enable_mcp",
        action="store_true",
        help="Enable MCP server",
    )
    parser.add_argument(
        "--enable-user-interaction",
        "--enable_user_interaction",
        dest="enable_user_interaction",
        action="store_true",
        help="Enable user interaction tasks (agent-user-interaction). Default: only GUI-only tasks",
    )
    parser.add_argument(
        "--scale-factor",
        "--scale_factor",
        dest="scale_factor",
        type=int,
        default=1000,
        help="Scale factor for coordinate conversion (default: 1000)",
    )


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configure the eval subcommand parser."""
    # Create eval parser with 'run' as an alias for backward compatibility
    eval_parser = subparsers.add_parser(
        "eval",
        aliases=["run"],
        help="Run benchmark evaluation suite",
    )

    _add_common_arguments(eval_parser)

    # Eval-specific arguments
    eval_parser.add_argument(
        "--task",
        "--tasks",
        dest="task",
        help='Specific task(s) to run (comma-separated) or "ALL" to run all tasks and generate statistics',
    )
    eval_parser.add_argument(
        "--max-retries",
        "--max_rounds",
        dest="max_retries",
        type=int,
        help="Maximum number of retries",
    )
    eval_parser.add_argument(
        "--dry-run",
        "--dry_run",
        dest="dry_run",
        action="store_true",
        help="Dry run the command, print final results only without executing tasks",
    )
    eval_parser.add_argument(
        "--max-concurrency",
        "--max_concurrency",
        dest="max_concurrency",
        type=int,
        default=None,
        help="Maximum number of concurrent tasks to run, Note: min(max_concurrency, number of tasks, number of docker envs)",
    )
    eval_parser.add_argument(
        "--shuffle-tasks",
        "--shuffle_tasks",
        dest="shuffle_tasks",
        action="store_true",
        help="Shuffle the order of tasks before running",
    )
    eval_parser.add_argument(
        "--seed",
        dest="seed",
        type=int,
        default=None,
        help="Random seed for reproducible AndroidWorld task params (only valid with --suite-family android_world)",
    )


async def execute(args: argparse.Namespace) -> None:
    """Execute the eval command."""
    log_file_root = args.log_file_root or args.output or "./traj_logs"

    # Validate --seed usage
    if getattr(args, "seed", None) is not None and args.suite_family != "android_world":
        raise ValueError("--seed is only supported with --suite-family android_world")

    # Check if running all tasks
    run_all_tasks = args.task and args.task.upper() == "ALL"
    if run_all_tasks:
        final_tasks = []
        logger.info("Running ALL tasks with statistics generation")
    else:
        final_tasks = args.task.split(",") if args.task else []

    start_time = time.time() if run_all_tasks else None

    # Parse aw_host URLs - if None, will auto-discover; if provided, split by comma
    aw_urls = None if args.aw_host is None else args.aw_host.split(",")

    task_results, task_list_with_no_results = run_agent_with_evaluation(
        agent_type=args.agent_type,
        model_name=args.model_name,
        llm_base_url=args.llm_base_url,
        log_file_root=log_file_root,
        tasks=final_tasks,
        max_step=args.max_round or -1,
        aw_urls=aw_urls,
        api_key=args.api_key or os.getenv("API_KEY"),
        executor_llm_base_url=args.executor_llm_base_url,
        executor_model_name=args.executor_model_name,
        executor_agent_class=args.executor_agent_class,
        device=args.device or "emulator-5554",
        step_wait_time=args.step_wait_time or 1.0,
        suite_family=args.suite_family or "mobile_world",
        seed=getattr(args, "seed", None),
        env_name_prefix=args.env_name_prefix,
        env_image=args.env_image,
        dry_run=args.dry_run,
        enable_mcp=args.enable_mcp,
        enable_user_interaction=args.enable_user_interaction,
        max_concurrency=args.max_concurrency,
        shuffle_tasks=args.shuffle_tasks,
        scale_factor=getattr(args, "scale_factor", 1000),
    )
    if run_all_tasks and task_results:
        total_duration = time.time() - start_time

        total_tasks = len(task_results)

        successful_tasks = sum(1 for result in task_results if result["score"] > 0.99)
        overall_success_rate = successful_tasks / total_tasks if total_tasks > 0 else 0.0

        report = {
            "summary": {
                "total_tasks_assigned": total_tasks + len(task_list_with_no_results),
                "total_tasks_with_results": total_tasks,
                "successful_tasks": successful_tasks,
                "total_tasks_with_no_results": len(task_list_with_no_results),
                "overall_success_rate": overall_success_rate,
                "total_duration_seconds": total_duration,
            },
            "metadata": {
                "agent_type": args.agent_type,
                "model_name": args.model_name,
                "timestamp": datetime.now().isoformat(),
                "log_file_root": log_file_root,
            },
            "tasks_with_results": task_results,
            "tasks_with_no_results": task_list_with_no_results,
        }

        output_path = Path(log_file_root)
        output_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = output_path / f"eval_report_{timestamp}.json"

        with open(report_file, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # Pretty print results using Rich
        console = Console()

        # Create summary panel
        summary_text = Text()
        summary_text.append("Evaluation Complete!\n\n", style="bold green")
        summary_text.append(f"Overall Success Rate: {overall_success_rate:.1%}\n", style="cyan")
        summary_text.append(
            f"Successful Tasks: {successful_tasks}/{total_tasks}\n", style="magenta"
        )
        summary_text.append(f"Total Duration: {total_duration:.1f} seconds\n", style="yellow")

        summary_panel = Panel(
            summary_text,
            title="[bold blue]📊 Evaluation Summary",
            border_style="blue",
            padding=(1, 2),
        )

        console.print(summary_panel)

        # Create detailed stats table
        stats_table = Table(
            title="[bold]📈 Detailed Statistics", show_header=True, header_style="bold blue"
        )
        stats_table.add_column("Metric", style="cyan", width=25)
        stats_table.add_column("Value", style="magenta", justify="right")

        stats_table.add_row("Total Tasks Assigned", str(report["summary"]["total_tasks_assigned"]))
        stats_table.add_row(
            "Tasks with Results", str(report["summary"]["total_tasks_with_results"])
        )
        stats_table.add_row("Successful Tasks", str(report["summary"]["successful_tasks"]))
        stats_table.add_row(
            "Tasks with No Results", str(report["summary"]["total_tasks_with_no_results"])
        )
        stats_table.add_row("Success Rate", f"{report['summary']['overall_success_rate']:.1%}")

        console.print(stats_table)

        # Create metadata panel
        metadata_text = Text()
        metadata_text.append(f"Agent Type: {report['metadata']['agent_type']}\n", style="green")
        metadata_text.append(f"Model: {report['metadata']['model_name'] or 'N/A'}\n", style="green")
        metadata_text.append(f"Timestamp: {report['metadata']['timestamp']}\n", style="green")
        metadata_text.append(f"Log Root: {report['metadata']['log_file_root']}\n", style="green")

        metadata_panel = Panel(
            metadata_text, title="[bold]🔧 Configuration", border_style="green", padding=(1, 2)
        )

        console.print(metadata_panel)

        # Show task results if available
        if task_results:
            results_table = Table(
                title="[bold]📋 Task Results", show_header=True, header_style="bold magenta"
            )
            results_table.add_column("Task", style="cyan", width=30)
            results_table.add_column("Score", style="green", justify="center")
            results_table.add_column("Status", style="yellow", justify="center")

            for result in task_results:
                status = "✅ Success" if result["score"] > 0.99 else "❌ Failed"
                status_style = "green" if result["score"] > 0.99 else "red"
                results_table.add_row(
                    result.get("task_name", "Unknown"),
                    f"{result['score']:.3f}",
                    f"[{status_style}]{status}[/{status_style}]",
                )

            console.print(results_table)

        # Show tasks with no results if any
        if task_list_with_no_results:
            no_results_text = Text()
            no_results_text.append("Tasks with no results:\n", style="bold red")
            for task in task_list_with_no_results[:5]:  # Show first 5
                no_results_text.append(f"• {task}\n", style="red")
            if len(task_list_with_no_results) > 5:
                no_results_text.append(
                    f"... and {len(task_list_with_no_results) - 5} more", style="red"
                )

            no_results_panel = Panel(
                no_results_text,
                title="[bold red]⚠️  Tasks with No Results",
                border_style="red",
                padding=(1, 2),
            )
            console.print(no_results_panel)

        # File locations panel
        files_text = Text()
        files_text.append(f"Results JSON: {report_file}\n", style="blue")
        files_text.append(f"Trajectory Logs: {log_file_root}", style="blue")

        files_panel = Panel(
            files_text, title="[bold]💾 Output Files", border_style="cyan", padding=(1, 2)
        )

        console.print(files_panel)
