"""Wraps AndroidWorld TaskEval as MobileWorld BaseTask."""

import random
import time

from loguru import logger

from mobile_world.runtime.app_helpers.system import time_sync_to_now
from mobile_world.runtime.aw_env_adapter import EnvAdapter
from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import execute_adb
from mobile_world.tasks.base import BaseTask


class AWTaskWrapper(BaseTask):
    """Wraps an AndroidWorld TaskEval to present a BaseTask-compatible interface.

    Overrides initialize_task() entirely to skip MobileWorld-specific cleanup
    (Mattermost/Mastodon/mall) that is irrelevant to AndroidWorld tasks.
    """

    start_on_home_screen = False  # AW tasks manage their own screen state

    def __init__(self, task_eval_class, params: dict = None, seed: int = None):
        # IMPORTANT: Must set up _task_eval BEFORE calling super().__init__()
        # because BaseTask.__init__ accesses self.app_names (abstract property).
        self._task_eval_class = task_eval_class
        self._seed = seed

        if params is not None:
            self._aw_params = params
        elif seed is not None:
            random.seed(seed)
            self._aw_params = task_eval_class.generate_random_params()
        else:
            self._aw_params = task_eval_class.generate_random_params()

        self._task_eval = task_eval_class(self._aw_params)
        self._env_adapter = None
        super().__init__()

    @property
    def app_names(self) -> set[str]:
        return set(self._task_eval.app_names)

    @property
    def goal(self) -> str:
        return self._task_eval.goal

    @property
    def snapshot_tag(self) -> str:
        return "aw_init_state"

    @property
    def task_tags(self) -> set[str]:
        return {"android_world"}

    @property
    def name(self) -> str:
        return self._task_eval.__class__.__name__

    @property
    def complexity(self) -> float:
        # Note: complexity is not part of BaseTask's interface but is needed
        # for the /task/complexity server endpoint (duck-typed).
        return self._task_eval.complexity

    def initialize_task(self, controller: AndroidController) -> bool | None:
        """Initialize task — full override, skips MobileWorld-specific cleanup.

        1. Loads aw_init_state snapshot
        2. Creates EnvAdapter wrapping the controller
        3. Calls AndroidWorld's TaskEval.initialize_task(env)
        4. Does NOT call MW cleanup (Mattermost/Mastodon/mall)
        5. Does NOT call initialize_user_agent_hook()
        6. Does NOT navigate to home screen
        """
        if self.initialized:
            logger.warning(f"{self.name} initialized before. Initializing again.")
            # Recreate TaskEval instance — AW TaskEvals refuse double init
            self._task_eval = self._task_eval_class(self._aw_params)

        # Load snapshot
        if self.snapshot_tag is not None:
            logger.debug(f"Loading snapshot: {self.snapshot_tag}")
            res = controller.load_snapshot(self.snapshot_tag)
            if not res:
                logger.error(f"Failed to load snapshot: {self.snapshot_tag}")
                return False
            controller.app_switch()
            controller.home()
            time.sleep(2)

        # Sync emulator time — AW snapshots freeze time which breaks
        # Chrome (SSL errors), Calendar, and other time-sensitive apps
        time_sync_to_now()

        adb = f"adb -s {controller.device}"
        # Prevent screen sleep during evaluation — UIAutomator dump fails
        # when screen is off, causing false negatives for Clock tasks etc.
        execute_adb(f"{adb} shell settings put system screen_off_timeout 2147483647")
        # Revoke calendar permissions so Simple Calendar Pro uses its internal
        # SQLite DB (which the evaluator reads) instead of system CalendarProvider
        execute_adb(f"{adb} shell pm revoke com.simplemobiletools.calendar.pro android.permission.READ_CALENDAR")
        execute_adb(f"{adb} shell pm revoke com.simplemobiletools.calendar.pro android.permission.WRITE_CALENDAR")
        # Disable Fossify Calendar to avoid the agent clicking the wrong calendar
        # app (Fossify has a green "Calendar" icon that conflicts with Simple Calendar Pro)
        execute_adb(f"{adb} shell pm disable-user --user 0 org.fossify.calendar")
        # Clear logcat so browser task success markers aren't stale
        execute_adb(f"{adb} logcat -c")
        # Enable Chrome renderer accessibility so UIAutomator can see WebView
        # content (needed for browser task evaluation)
        execute_adb(f'{adb} shell "echo chrome --force-renderer-accessibility > /data/local/tmp/chrome-command-line"')
        # Disable gallery apps to avoid confusing the agent — AW tasks use
        # Simple Gallery Pro, but other gallery apps have similar icons.
        execute_adb(f"{adb} shell pm disable-user --user 0 com.google.android.apps.photos")
        execute_adb(f"{adb} shell pm disable-user --user 0 gallery.photomanager.picturegalleryapp.imagegallery")

        # Set up A11y gRPC forwarder for robust UI state access.
        # Unlike UIAutomator dump, the AccessibilityService works even when
        # the screen is animating (e.g. running stopwatch/timer).
        from mobile_world.runtime.a11y_grpc_manager import get_manager
        a11y_mgr = get_manager()
        if not a11y_mgr.is_running:
            a11y_mgr.start_server()

        # Create adapter and delegate to AndroidWorld's initialization
        self._env_adapter = EnvAdapter(controller)
        # Set up the a11y forwarder on the device (install + enable + configure)
        a11y_mgr.setup_device(self._env_adapter.controller)
        try:
            logger.info(f"Initializing AndroidWorld task: {self.name}")
            self._task_eval.initialize_task(self._env_adapter)
        except Exception as e:
            logger.error(f"Failed to initialize AndroidWorld task {self.name}: {e}")
            return False

        controller.interaction_cache = ""
        controller.user_agent_chat_history = []
        self.initialized = True
        return True

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        self._check_is_initialized()
        env = self._env_adapter or EnvAdapter(controller)
        return self._task_eval.is_successful(env)

    def tear_down(self, controller: AndroidController) -> None:
        env = self._env_adapter or EnvAdapter(controller)
        try:
            self._task_eval.tear_down(env)
        except Exception as e:
            logger.warning(f"AndroidWorld tear_down failed for {self.name}: {e}")

        if self._env_adapter:
            self._env_adapter.cleanup()
            self._env_adapter = None

        super().tear_down(controller)
