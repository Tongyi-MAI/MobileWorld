"""Cancel meeting email task implementation."""

from pathlib import Path

from loguru import logger

from mobile_world.runtime.app_helpers.mail import get_sent_email_info
from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import execute_adb
from mobile_world.tasks.base import BaseTask


class CancelMeetingTask(BaseTask):
    goal = "Could you reply to Daniel's most recent email to tell him I'll have to cancel the meeting on Thursday?"

    correct_recipient = "dan123@gmail.com"
    body = {"cancel", "meeting"}

    task_tags = {"lang-en"}

    app_names = {
        "Mail",
    }

    def initialize_task_hook(self, controller: AndroidController) -> bool:
        """Inject test email and reset Mail app."""
        root_path = Path(__file__).resolve().parent
        local_json_path = root_path / "assets" / "cancelMeeting.json"

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
        """Check if the task succeeded by verifying the cancel meeting email was sent as a reply with."""
        self._check_is_initialized()

        email = get_sent_email_info()

        if email is None:
            return 0.0, "No email found"
        if not email["subject"] == "RE: Meeting Thursday":
            return 0.0, "Wrong subject"
        if email["to"].lower() != self.correct_recipient.lower():
            return 0.0, "Wrong recipient"
        contents = email["body"]
        for word in self.body:
            if word.lower() not in contents.lower():
                return 0.0, "Wrong body"
        return 1.0, "Correct email sent"
