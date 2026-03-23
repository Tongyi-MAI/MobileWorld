import os
import random
import threading
import time
from queue import Queue

from dotenv import load_dotenv
from joblib import Parallel, delayed
from loguru import logger

from mobile_world.agents.base import BaseAgent, MCPAgent
from mobile_world.agents.registry import create_agent
from mobile_world.runtime.client import (
    AndroidEnvClient,
    AndroidMCPEnvClient,
    scan_finished_tasks,
)
from mobile_world.runtime.utils.docker import (
    discover_backends,
)
from mobile_world.runtime.utils.models import ANSWER, ENV_FAIL, FINISHED, UNKNOWN
from mobile_world.runtime.utils.trajectory_logger import TrajLogger

load_dotenv()


def _execute_single_task(
    env: AndroidEnvClient,
    agent: BaseAgent,
    task_name: str,
    max_step: int,
    traj_logger: TrajLogger,
    enable_mcp: bool = False,
) -> tuple[int, float]:
    """Execute a single task and return the number of steps and score.

    Returns:
        tuple[int, float]: (number of steps, score)
    """

    logger.debug(f"max_step: {max_step}")

    if enable_mcp and not isinstance(agent, MCPAgent):
        logger.error(
            "MCP is enabled but agent type is not a MCP agent. Please use a MCP agent type."
        )

    if enable_mcp:
        traj_logger.log_tools(env.tools)
    task_goal = env.get_task_goal(task_type=task_name)

    logger.debug(f"task_goal: {task_goal}")

    step = 0
    obs = env.initialize_task(task_name=task_name)
    agent.initialize(task_goal)

    while True:
        step += 1

        logger.debug(f"Screenshot captured in step {step}")

        prediction, action = agent.predict(
            {
                "screenshot": obs.screenshot,
                "tool_call": obs.tool_call,
                "ask_user_response": obs.ask_user_response,
            }
        )  # for backward compatibility
        traj_logger.log_traj(
            task_name,
            task_goal,
            step,
            prediction,
            action.model_dump(exclude_none=True),
            obs,
            agent.get_total_token_usage(),
        )
        if prediction is None:
            logger.warning(f"Agent prediction failed in step {step}")
            break

        terminate = False
        logger.debug(f"current step {step}")

        if action.action_type in [ENV_FAIL, FINISHED, UNKNOWN]:
            logger.debug(f"task terminated in step {step} with action {action.action_type}")
            terminate = True
        elif action.action_type in [ANSWER]:
            logger.debug(f"answer triggered, execution action {action}")
            obs = env.execute_action(action)
            terminate = True
        else:
            logger.debug(f"execution action {action}")
            obs = env.execute_action(action)
        if terminate:
            break

        if step >= max_step:
            logger.debug("task steps reach max step, terminate")
            break

    score, reason = env.get_task_score(task_type=task_name)
    logger.debug(f"task_score: {score}, reason: {reason}")
    traj_logger.log_score(score=score, reason=reason)

    res = env.tear_down_task(task_type=task_name)
    agent.done()
    logger.debug(f"tear_down_task response: {res}")

    return step, score


def _process_task_on_env(
    task_name: str,
    env_queue: Queue,
    agent_type: str,
    model_name: str,
    llm_base_url: str,
    api_key: str | None,
    log_file_root: str,
    max_step: int,
    retry_on_device_unhealthy: int = 2,
    enable_mcp: bool = False,
    **kwargs,
) -> dict:
    """Process a single task on a specific environment.

    Args:
        task_name: Name of the task to execute
        env_url: URL of the environment to use
        agent_type: Type of agent to create
        model_name: Model name for the agent
        llm_base_url: LLM service base URL
        api_key: API key for LLM service
        log_file_root: Root directory for log files
        max_step: Maximum steps for task execution
        **kwargs: Additional kwargs for agent creation

    Returns:
        dict: Task result containing task_name, success, score, steps, duration_seconds
    """
    # Create thread-specific log file
    thread_id = threading.current_thread().ident
    thread_log_file = os.path.join(log_file_root, task_name, f"thread_{thread_id}.log")
    os.makedirs(os.path.dirname(thread_log_file), exist_ok=True)
    traj_logger = TrajLogger(log_file_root, task_name)

    def thread_filter(record):
        return record["extra"].get("thread_id") == thread_id

    thread_handler_id = logger.add(
        thread_log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | container: {extra[container_name]} | {message}",
        level="DEBUG",
        enqueue=True,
        filter=thread_filter,
    )
    env, container_name = env_queue.get()

    try:
        with logger.contextualize(thread_id=thread_id, container_name=container_name):
            logger.info("Processing task '{}' on environment {}", task_name, env.base_url)
            if enable_mcp:
                assert isinstance(env, AndroidMCPEnvClient), (
                    f"env must be a AndroidMCPEnvClient, but got {type(env)}"
                )
                try:
                    env.reset_tools(task_type=task_name)
                except Exception as e:
                    logger.exception(f"Error resetting tools for task {task_name}: {e}")
                    return None

            agent = create_agent(agent_type, model_name, llm_base_url, api_key, env=env, **kwargs)

            task_start_time = time.time()
            while True:
                try:
                    task_steps, task_score = _execute_single_task(
                        env,
                        agent,
                        task_name,
                        max_step,
                        traj_logger=traj_logger,
                        enable_mcp=enable_mcp,
                    )
                    break
                except Exception as e:
                    if "Device is not healthy" in str(e) and retry_on_device_unhealthy > 0:
                        logger.warning("Device is not healthy, retrying...")
                        time.sleep(20)
                        retry_on_device_unhealthy -= 1
                        traj_logger.reset_traj()
                        continue
                    else:
                        logger.exception(f"Error executing task {task_name}")
                        return None

            task_duration = time.time() - task_start_time
            task_success = task_score > 0.0

            logger.info(
                "Task '{}' completed on {}: success={}, score={}, steps={}, duration={:.1f}s",
                task_name,
                env.base_url,
                task_success,
                task_score,
                task_steps,
                task_duration,
            )

            return {
                "task_name": task_name,
                "score": task_score,
            }
    finally:
        # Remove the thread-specific handler
        logger.remove(thread_handler_id)
        env_queue.put((env, container_name))


def _init_env(
    env_url: str, device: str, step_wait_time: float, suite_family: str, enable_mcp: bool,
    seed: int = None,
) -> AndroidEnvClient:
    """Initialize the environment."""
    if enable_mcp:
        env = AndroidMCPEnvClient(env_url, device, step_wait_time=step_wait_time)
    else:
        env = AndroidEnvClient(env_url, device, step_wait_time=step_wait_time)
    env.switch_suite_family(suite_family, seed=seed)
    return env


def run_agent_with_evaluation(
    agent_type: str,
    model_name: str,
    llm_base_url: str,
    log_file_root: str,
    tasks: list[str],
    max_step: int = -1,
    aw_urls: list[str] | None = None,
    api_key: str | None = None,
    device: str = "emulator-5554",
    step_wait_time: float = 1.0,
    suite_family: str = "mobile_world",
    seed: int = None,
    env_name_prefix: str = "mobile_world_env",
    env_image: str = "mobile_world",
    dry_run: bool = False,
    enable_mcp: bool = False,
    enable_user_interaction: bool = False,
    max_concurrency: int | None = None,
    shuffle_tasks: bool = False,
    **kwargs,
) -> list[dict]:
    """Run the agent and return the evaluation results.

    Args:
        agent_type: Type of agent to use
        model_name: Model name for the agent
        llm_base_url: LLM service base URL
        log_file_root: Root directory for log files
        tasks: List of task names to execute (empty list for all tasks)
        max_step: Maximum steps for task execution
        aw_urls: List of Android World backend URLs. If None, auto-discover from containers
        api_key: API key for LLM service
        device: Android device ID
        step_wait_time: Wait time after each step
        suite_family: Suite family to use
        **kwargs: Additional kwargs for agent creation

    Returns:
        list[dict]: The evaluation results for each task, containing task_name, success, score, steps, duration_seconds, env_url
    """

    container_names = None
    if aw_urls is None or len(aw_urls) == 0:
        logger.info("No backend URLs specified, auto-discovering from containers...")
        aw_urls, container_names = discover_backends(image_filter=env_image, prefix=env_name_prefix)
        logger.info("Container names: {}", container_names)
        if not aw_urls:
            logger.error("No backend URLs found. Please start containers or specify --aw-host")
            return [], []

    logger.info("Using {} backend URL(s): {}", len(aw_urls), aw_urls)

    envs = Parallel(
        n_jobs=min(max_concurrency if max_concurrency is not None else len(aw_urls), len(aw_urls)),
        backend="threading",
    )(
        delayed(_init_env)(env_url, device, step_wait_time, suite_family, enable_mcp, seed=seed)
        for env_url in aw_urls
    )

    if len(tasks) != 0:
        task_list = tasks
    else:
        task_list = envs[0].get_suite_task_list(enable_mcp=enable_mcp, enable_user_interaction=enable_user_interaction)

    logger.info("Task list: {} ({} tasks)", task_list, len(task_list))

    finished_task_list, finished_scores = scan_finished_tasks(log_file_root, task_list)
    logger.info("Finished task list: {} ({} tasks)", finished_task_list, len(finished_task_list))

    task_list = [task for task in task_list if task not in finished_task_list]
    logger.info("Remaining tasks to execute: {} ({} tasks)", task_list, len(task_list))

    num_envs = len(envs)
    logger.info("Distributing {} tasks across {} environment(s)", len(task_list), num_envs)

    env_queue = Queue[tuple[AndroidEnvClient, str | None]](maxsize=num_envs)
    for i, env in enumerate(envs):
        env_queue.put((env, container_names[i] if container_names else None))

    logger.info("Starting parallel task execution with threading backend...")

    if shuffle_tasks:
        random.shuffle(task_list)
    if not dry_run:
        task_results = Parallel(
            n_jobs=min(max_concurrency if max_concurrency is not None else num_envs, num_envs),
            backend="threading",
        )(
            delayed(_process_task_on_env)(
                task_name=task_name,
                env_queue=env_queue,
                agent_type=agent_type,
                model_name=model_name,
                llm_base_url=llm_base_url,
                api_key=api_key,
                log_file_root=log_file_root,
                max_step=max_step,
                enable_mcp=enable_mcp,
                **kwargs,
            )
            for task_name in task_list
        )
    else:
        logger.info("Dry run mode, skipping task execution")
        task_results = []

    task_list_with_no_results = [
        task_name for task_name, task_result in zip(task_list, task_results) if task_result is None
    ]
    logger.info(f"Task with no results count: {len(task_list_with_no_results)}")
    success_task_results = [task_result for task_result in task_results if task_result is not None]

    for finished_task_name, finished_score in zip(finished_task_list, finished_scores):
        success_task_results.append(
            {
                "task_name": finished_task_name,
                "score": finished_score,
            }
        )

    return (success_task_results, task_list_with_no_results)
