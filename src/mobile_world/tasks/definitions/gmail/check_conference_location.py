"""Check conference location task implementation."""

from pathlib import Path

from loguru import logger

from mobile_world.runtime.app_helpers.system import check_sms_via_adb
from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import execute_adb
from mobile_world.tasks.base import BaseTask


class CheckConferenceLocationTask(BaseTask):
    goal = (
        "Check my email for the location of the MCFT conference hotel, then text the address to Tom (4456547865)."
        "Use Google maps to tell me how long it would take to walk from the MIT Stata center to there. Only response the time in minutes. No other text."
    )
    correct_phone_number = "4456547865"
    expected_message_partials = [
        "110 Mt Auburn St",
        "110 Mt. Auburn St.",
        "110 Mount Auburn St",
        "110 Mount Auburn Street",
    ]

    correct_walk_time = 43
    tolerance_minutes = 10

    task_tags = {"lang-en"}

    app_names = {"Messages", "Maps"}

    def initialize_task_hook(self, controller: AndroidController) -> bool:
        """Inject test email and reset Mail app."""
        root_path = Path(__file__).resolve().parent
        local_json_path = root_path / "assets" / "checkConferenceLocation.json"

        remote_json_path = "/sdcard/Android/data/com.gmailclone/files/state.json"

        if not local_json_path.exists():
            logger.error(f"Email state file not found: {local_json_path}")
            return False

        result = execute_adb(f"push {local_json_path} {remote_json_path}")
        if not result.success:
            logger.error(f"Failed to push email JSON to emulator: {result.error}")
            return False

        result1 = execute_adb("shell am force-stop com.gmailclone")
        result2 = execute_adb("shell am start -n com.gmailclone/.MainActivity")
        if not result1.success or not result2.success:
            logger.warning(
                f"Failed to restart Mail app: {result1.error if not result1.success else result2.error}"
            )

        logger.info("Successfully injected emails and restarted Mail app.")
        return True

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        """Check if the correct address is sent and the correct travel time is given."""
        self._check_is_initialized()

        results = []
        for partial in self.expected_message_partials:
            result = check_sms_via_adb(
                controller,
                phone_number=self.correct_phone_number,
                content=partial,
            )
            results.append(result)

        if any(results):
            logger.info(
                f"Successfully found SMS to {self.correct_phone_number} with correct content"
            )
        else:
            return 0.0, f"SMS to {self.correct_phone_number} with correct content not found"

        answer = (controller.interaction_cache or "").strip()
        print(f"answer: {answer}")

        if not answer or not answer.isdigit():
            return 0.0, "no answer or not a number"

        answer_minutes = int(answer)

        if abs(answer_minutes - self.correct_walk_time) <= self.tolerance_minutes:
            return 1.0, "success"
        else:
            return (
                0.0,
                "incorrect walk time, expected {self.correct_walk_time} minutes, got {answer_minutes} minutes, tolerance {self.tolerance_minutes} minutes",
            )
