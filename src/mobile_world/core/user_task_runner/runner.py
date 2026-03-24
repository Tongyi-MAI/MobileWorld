"""User task runner for executing single disposable tasks."""

import json
import os
import sys
import threading
import time
from datetime import datetime

from loguru import logger
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from mobile_world.agents.base import BaseAgent
from mobile_world.agents.registry import create_agent
from mobile_world.runtime.client import AndroidEnvClient, AndroidMCPEnvClient
from mobile_world.runtime.utils.models import (
    ANSWER,
    ASK_USER,
    ENV_FAIL,
    FINISHED,
    UNKNOWN,
    Observation,
)
from mobile_world.runtime.utils.trajectory_logger import TrajLogger

from .prerequisite import env_cleanup, env_validation

_console = Console()


def _ask_user_interactive(question: str) -> str:
    """Prompt user for input via terminal using rich."""
    _console.print()
    panel = Panel(
        question,
        title="[bold blue]🤖 Agent Question",
        border_style="blue",
        padding=(1, 2),
    )
    _console.print(panel)

    response = Prompt.ask("[bold green]Your response[/bold green]")
    _console.print()

    return response


def _format_action(action) -> str:
    """Format action for display."""
    parts = [f"[bold cyan]{action.action_type}[/bold cyan]"]

    if action.x is not None and action.y is not None:
        parts.append(f"at ({action.x}, {action.y})")
    if action.text:
        parts.append(f'text="{action.text}"')
    if action.direction:
        parts.append(f"direction={action.direction}")
    if action.app_name:
        parts.append(f"app={action.app_name}")
    if action.goal_status:
        parts.append(f"status={action.goal_status}")
    if action.action_name:
        parts.append(f"mcp_tool={action.action_name} args={action.action_json}")

    return " ".join(parts)


def _print_step_header(step: int, max_step: int) -> None:
    """Print step header."""
    step_info = f"Step {step}" if max_step <= 0 else f"Step {step}/{max_step}"
    _console.rule(f"[bold yellow]{step_info}[/bold yellow]", style="yellow")


def _print_observation(obs: Observation) -> None:
    """Print observation summary."""
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="dim")
    table.add_column("Value")

    table.add_row(
        "📸 Screenshot", "[green]captured[/green]" if obs.screenshot else "[red]none[/red]"
    )

    if obs.ask_user_response:
        table.add_row("💬 User Response", f"[cyan]{obs.ask_user_response}[/cyan]")

    if obs.tool_call:
        tool_result = str(obs.tool_call)[:500]
        if len(str(obs.tool_call)) > 500:
            tool_result += "..."
        table.add_row("🔧 Tool Call", f"[green]{tool_result}[/green]")

    _console.print(
        Panel(table, title="[bold blue]Observation", border_style="blue", padding=(0, 1))
    )


def _print_agent_response(prediction: str | None, action) -> None:
    """Print agent prediction and action."""
    if prediction:
        if "Action:" in prediction:
            thinking_text = prediction.split("Action:")[0]
            thinking_text = thinking_text.replace("Thought:", "").strip()
        else:
            thinking_text = prediction
        _console.print(
            Panel(
                Text(thinking_text, style="italic"),
                title="[bold magenta]💭 Agent Thinking",
                border_style="magenta",
                padding=(0, 1),
            )
        )

    action_text = _format_action(action)
    _console.print(
        Panel(
            action_text,
            title="[bold green]⚡ Action",
            border_style="green",
            padding=(0, 1),
        )
    )


def _print_task_start(goal: str) -> None:
    """Print task start banner."""
    _console.print()
    _console.print(
        Panel(
            f"[bold white]{goal}[/bold white]",
            title="[bold cyan]🎯 Task Goal",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    _console.print()


def _print_task_end(step: int, action_type: str) -> None:
    """Print task completion summary."""
    _console.print()

    status_style = (
        "green" if action_type == FINISHED else "yellow" if action_type == ANSWER else "red"
    )
    status_icon = "✅" if action_type == FINISHED else "📝" if action_type == ANSWER else "⚠️"

    _console.print(
        Panel(
            f"[bold]Completed in [cyan]{step}[/cyan] steps with status: [{status_style}]{status_icon} {action_type}[/{status_style}][/bold]",
            title="[bold green]Task Complete",
            border_style="green",
            padding=(0, 2),
        )
    )
    _console.print()


def _execute_user_task(
    env: AndroidEnvClient,
    agent: BaseAgent,
    goal: str,
    max_step: int,
    traj_logger: TrajLogger | None = None,
    enable_mcp: bool = False,
) -> int:
    """Execute a single user-defined task."""
    logger.debug(f"Executing user task with max_step={max_step}")

    if enable_mcp and traj_logger:
        traj_logger.log_tools(env.tools)

    logger.info(f"Task goal: {goal}")
    _print_task_start(goal)

    step = 0
    last_action_type = UNKNOWN
    obs_dict = env.get_observation(type="screenshot", wait_to_stabilize=True)
    obs = Observation(screenshot=obs_dict["screenshot"], ask_user_response=None)

    agent.initialize(goal)

    while True:
        step += 1
        logger.debug(f"Step {step}")
        _print_step_header(step, max_step)
        _print_observation(obs)

        with Live(
            Spinner("dots", text="[bold cyan]Agent thinking...[/bold cyan]"),
            console=_console,
            transient=True,
        ):
            prediction, action = agent.predict(
                {
                    "screenshot": obs.screenshot,
                    "tool_call": obs.tool_call,
                    "ask_user_response": obs.ask_user_response,
                }
            )

        if traj_logger:
            traj_logger.log_traj(
                "user_task",
                goal,
                step,
                prediction,
                action.model_dump(exclude_none=True),
                obs,
                agent.get_total_token_usage(),
            )

        if prediction is None:
            logger.warning(f"Agent prediction failed in step {step}")
            _console.print("[bold red]⚠️ Agent prediction failed[/bold red]")
            break

        _print_agent_response(prediction, action)
        last_action_type = action.action_type

        terminate = False

        if action.action_type in [ENV_FAIL, FINISHED, UNKNOWN]:
            terminate = True
        elif action.action_type == ASK_USER:
            question = action.text or "The agent needs your input"
            user_response = _ask_user_interactive(question)

            screenshot = env.get_screenshot(wait_to_stabilize=True)
            obs = Observation(screenshot=screenshot, ask_user_response=user_response)
        elif action.action_type == ANSWER:
            obs = env.execute_action(action)
            terminate = True
        else:
            obs = env.execute_action(action)

        if terminate:
            break

        if max_step > 0 and step >= max_step:
            _console.print("[bold yellow]⏱️ Max steps reached[/bold yellow]")
            break

    agent.done()
    logger.info(f"User task completed in {step} steps")
    _print_task_end(step, last_action_type)

    return step


def run_user_task(
    goal: str,
    agent_type: str,
    model_name: str,
    llm_base_url: str,
    log_file_root: str | None = None,
    max_step: int = -1,
    aw_url: str | None = None,
    api_key: str | None = None,
    device: str = "emulator-5554",
    step_wait_time: float = 1.0,
    suite_family: str = "mobile_world",
    env_name_prefix: str = "mobile_world_env",
    env_image: str = "mobile_world",
    enable_mcp: bool = False,
    log_verbose: bool = False,
    **kwargs,
) -> dict:
    """Run a single user-defined task.

    Args:
        goal: User-provided task goal/instruction
        agent_type: Type of agent to use
        model_name: Model name for the agent
        llm_base_url: LLM service base URL
        log_file_root: Optional root directory for log files
        max_step: Maximum steps for task execution (-1 for unlimited)
        aw_url: Android World backend URL (auto-discovered if None)
        api_key: API key for LLM service
        device: Android device ID
        step_wait_time: Wait time after each step
        suite_family: Suite family to use
        env_name_prefix: Container name prefix for auto-discovery
        env_image: Container image name for auto-discovery
        enable_mcp: Whether to enable MCP tools
        **kwargs: Additional kwargs for agent creation

    Returns:
        dict: Result containing steps executed and duration
    """
    aw_url = env_validation(aw_url, device)
    if not log_verbose:
        logger.remove()

    if enable_mcp:
        env = AndroidMCPEnvClient(aw_url, device, step_wait_time=step_wait_time)

        _console.print(
            f"[bold cyan]🔧 Loaded MCP tools:[/bold cyan] {[t['name'] for t in env.tools]}"
        )

    else:
        env = AndroidEnvClient(aw_url, device, step_wait_time=step_wait_time)

    env.switch_suite_family(suite_family)

    traj_logger = None
    log_handler_id = None
    if log_file_root:
        task_log_dir = os.path.join(log_file_root, "user_task")
        os.makedirs(task_log_dir, exist_ok=True)

        # Write metadata.json at log root for suite family identification
        metadata_path = os.path.join(log_file_root, "metadata.json")
        if not os.path.exists(metadata_path):
            metadata = {
                "suite_family": "user_task",
                "agent_type": agent_type,
                "model_name": model_name,
                "timestamp": datetime.now().isoformat(),
            }
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

        thread_id = threading.current_thread().ident
        thread_log_file = os.path.join(task_log_dir, f"thread_{thread_id}.log")

        log_handler_id = logger.add(
            thread_log_file,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
            level="DEBUG",
            enqueue=True,
        )
        traj_logger = TrajLogger(log_file_root, "user_task")

    agent = create_agent(agent_type, model_name, llm_base_url, api_key, env=env, **kwargs)

    start_time = time.time()
    try:
        steps = _execute_user_task(
            env,
            agent,
            goal,
            max_step,
            traj_logger=traj_logger,
            enable_mcp=enable_mcp,
        )
        duration = time.time() - start_time

        return {
            "success": True,
            "steps": steps,
            "duration_seconds": duration,
            "goal": goal,
        }

    except Exception as e:
        logger.exception(f"Error executing user task: {e}")
        return {
            "success": False,
            "error": str(e),
            "goal": goal,
        }
    finally:
        if log_handler_id is not None:
            logger.remove(log_handler_id)

        logger.add(sys.stderr)

        env_cleanup(device)
