from loguru import logger

from mobile_world.runtime.app_helpers.system import check_sms_via_adb
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class CheckConferenceAndSendSmsTask2(BaseTask):
    """Check calendar for Paris trip dates and send SMS notification to Mia Scott."""

    goal = "Check my calendar and send an SMS notification to Mia with the dates of my arrival and departure from Tokyo. The message should contain only the two dates in MM/DD/YYYY format, separated by a comma."
    correct_phone_number = "+14058298746"  # Mia Scott's phone number: +1-405-829-8746
    expected_message_content = ["10/04/2025", "10/10/2025"]  # Allow space after comma

    task_tags = {"lang-en"}

    app_names = {"Calendar", "Messages"}

    def initialize_task_hook(self, controller: AndroidController) -> bool:
        self.relevant_information = "Mia Scott's phone number can be found in the Contacts app."
        return True

    def is_successful(self, controller: AndroidController) -> tuple[float, str]:
        self._check_is_initialized()

        result = check_sms_via_adb(
            controller,
            phone_number=self.correct_phone_number,
            content=self.expected_message_content,
        )

        if result:
            logger.info(
                f"Successfully found SMS to Mia Scott ({self.correct_phone_number}) with correct dates: {self.expected_message_content}"
            )
            return 1.0, "Success"
        else:
            logger.info(
                f"SMS to Mia Scott ({self.correct_phone_number}) with correct dates not found"
            )
            return 0.0, f"SMS to {self.correct_phone_number} with correct dates not found"
