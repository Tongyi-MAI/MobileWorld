"""Interface for a task and the evaluation logic for that task."""

import abc
import asyncio
import os
import time
from datetime import datetime
from typing import Any

from loguru import logger

from mobile_world.runtime.app_helpers import mastodon, mattermost
from mobile_world.runtime.app_helpers.mall import (
    clear_callback_files,
    clear_config,
)
from mobile_world.runtime.app_helpers.system import (
    time_sync_to_now,
)
from mobile_world.runtime.controller import AndroidController


class BaseTask(abc.ABC):
    start_on_home_screen = True

    def __init__(self, params: dict[str, Any] = None):
        if params is None:
            params = {}
        self.initialized = False
        self._params = params
        self.apps_require_time_sync = ["Chrome", "Maps", "MCP-arXiv"]
        self.current_date = self._compute_current_date()

    @property
    def task_tags(self) -> set[str]:
        """The tags of the task."""
        return set()

    @property
    def name(self) -> str:
        """The name of the task."""
        return self.__class__.__name__

    @property
    @abc.abstractmethod
    def app_names(self) -> set[str]:
        """The names of the apps that the agent will be interacting with during the task."""

    @property
    @abc.abstractmethod
    def goal(self) -> str:
        """The goal of the task."""

    @property
    def snapshot_tag(self) -> str | None:
        """tag name of the snapshot to use for this task"""
        return "init_state"

    def initialize_task_hook(self, controller: AndroidController) -> bool | None:
        logger.info(f"Initializing default task hook for {self.name}, will reset system time")
        time_sync_to_now()
        return True

    def initialize_user_agent_hook(self, controller: AndroidController) -> bool | None:
        """Initialize the user agent for answering questions from the mobile GUI agent."""

        if not hasattr(self, "relevant_information"):
            self.relevant_information = "No more task-related information can be provided."

        user_sys_prompt = (
            f"You are acting as a mobile phone user. "
            f"An mobile GUI agent is executing a task on your phone. "
            f"The task goal is: {self.goal}. "
            f"You need to answer questions from the mobile GUI agent. "
            f"The relevant information for the task is: {self.relevant_information}. "
            f"If the question is not related to the task or no more task-related information is available, you need to refuse to answer in a polite manner."
            f"DO NOT make up any information. You can ONLY give the answer based on the relevant information and the task goal."
            f"Today is {self.current_date}. If the question is about the date, you need to answer the correct date based on the current date."
        )

        controller.user_sys_prompt = user_sys_prompt

        if not hasattr(self, "model_config") or self.model_config is None:
            from mobile_world.tasks.utils import ModelConfig

            controller.model_config = ModelConfig(
                model_name=os.getenv("USER_AGENT_MODEL", "gpt-4o-mini"),
                api_key=os.getenv("USER_AGENT_API_KEY", ""),
                url=os.getenv("USER_AGENT_BASE_URL", "https://api.openai.com/v1"),
            )
        else:
            controller.model_config = self.model_config

        logger.info(
            f"[TASK_INIT] Configured user agent with model: {controller.model_config.model_name}"
        )

        return True

    def _compute_current_date(self) -> str:
        """The date the task presents as 'today'. Recomputed each episode so a
        long-lived singleton instance doesn't freeze it at process-boot time."""
        needs_time_sync = any(app in self.apps_require_time_sync for app in self.app_names)
        return datetime.now().date().strftime("%Y-%m-%d") if needs_time_sync else "2025-10-16"

    def reset_task_state(self) -> None:
        """Clear per-episode mutable state. Override in tasks that accumulate it.

        The registry reuses one singleton instance per task class, so this runs at
        the start of every initialize_task() to stop state leaking across episodes.
        """

    def initialize_task(self, controller: AndroidController) -> bool | None:
        """Initializes the task."""
        self.reset_task_state()
        self.current_date = self._compute_current_date()  # refresh per episode (singleton reuse)
        if self.initialized:
            logger.warning(f"{self.name} initialized before. Initializing again.")

        if self.snapshot_tag is not None:
            logger.debug(f"Loading snapshot: {self.snapshot_tag}")
            res = controller.load_snapshot(self.snapshot_tag)
            if not res:
                logger.error(f"Failed to load snapshot: {self.snapshot_tag}")
                return False
            # bug fix: it seems a few keystrokes are needed to force re-rendering the screen
            controller.app_switch()
            controller.home()
            time.sleep(2)

        # some apps require time sync, e.g. Chrome, Maps, MCP-Amap
        if any(app in self.apps_require_time_sync for app in self.app_names):
            logger.info(f"Syncing time for {self.name}")
            if not time_sync_to_now():
                logger.error(f"Failed to sync time for {self.name}")
                return False

        ### app specific initialization, run before initialize_task_hook ###
        ### in case some tasks forget to implement proper tear_down() ###
        mattermost.stop_mattermost_backend()
        mastodon.stop_mastodon_backend()
        clear_config()
        clear_callback_files(controller.device)

        logger.info(f"Initializing {self.name}")
        init_hook_res = self.initialize_task_hook(controller)
        if isinstance(init_hook_res, bool) and not init_hook_res:
            # only raise error if the task hook explicitly returns False, otherwise continue for True or None
            logger.error(f"Failed to initialize task hook for {self.name}")
            return False

        self.initialize_user_agent_hook(controller)

        if self.start_on_home_screen:
            controller.home()

        controller.interaction_cache = ""
        controller.user_agent_chat_history = []
        self.initialized = True
        return True

    def _check_is_initialized(self) -> None:
        if not self.initialized:
            raise RuntimeError(
                f"{self.name}.initialize_task() must be called before {self.name}.is_successful()."
            )

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:  # pylint: disable=unused-argument
        """Determines if the task is successful.

        Args:
          env:

        Returns:
          (0.0, "reason"): Not successful.
          (1.0, "reason"): Task is successful.
        """
        if type(self).is_successful is BaseTask.is_successful:
            assert type(self).is_successful_async is not BaseTask.is_successful_async, (
                "Subclasses must implement this method or is_successful_async method"
            )
            return asyncio.run(self.is_successful_async(controller))
        else:
            return self.is_successful(controller)

    async def is_successful_async(self, controller: AndroidController) -> float | tuple[float, str]:
        """Determines if the task is successful asynchronously."""
        # If subclass overrode this method, just use it
        if type(self).is_successful_async is not BaseTask.is_successful_async:
            # subclass provided its own async implementation
            return await self._is_successful_async_impl(controller)

        # Fallback: run sync implementation in a thread so we don't block the event loop
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.is_successful, controller)

    def tear_down(self, controller: AndroidController) -> None:  # pylint: disable=unused-argument
        """Tears down the task."""
        controller.interaction_cache = ""
        controller.user_sys_prompt = None
        controller.model_config = None
        controller.user_agent_chat_history = []
        self.initialized = False
        logger.info(f"Tearing down {self.name}")

        return True

    def run_task(self, agent_question: str = None) -> bool | None:
        from mobile_world.tasks.utils import wait_for_execution

        controller = AndroidController(device="emulator-5554")

        print("Initializing task...")
        status = self.initialize_task(controller)
        print(f"Initialize Status: {status}")

        if agent_question:
            answer = controller.ask_user(agent_question)
            print(f"Agent Question: {agent_question}")
            print(f"Answer: {answer}")

        wait_for_execution(controller)

        score = self.is_successful(controller)
        print(f"Final Success Score: {score}")

        status = self.tear_down(controller)
        print(f"Tear down Status: {status}")
