import re

from loguru import logger

from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class CheckConferenceDurationTask(BaseTask):
    """Check how many days of conference meetings were scheduled in October."""

    goal = "How many days of conference meetings did I schedule in October? Please only return the number of days, no other text."
    correct_answer = "12"

    task_tags = {"lang-en"}
    app_names = {"Calendar"}

    def initialize_task_hook(self, controller: AndroidController) -> bool:
        self.relevant_information = "I always schedule conference meetings in the Calendar app."
        return True

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        self._check_is_initialized()

        answer = str(controller.interaction_cache)

        # --- [Start of Answer Verification Logic] ---

        # 1. Noise Cleaning
        # Use r"" (Raw String) to resolve SyntaxWarning

        # (A) Remove time patterns (e.g., 12:00, 12:30) -> replace with empty string
        # \d{1,2} matches 1 to 2 digits
        clean_text = re.sub(r"\d{1,2}:\d{2}", "", answer)

        # (B) Remove date slash/dash patterns (e.g., 10/12, 2023-10-12)
        clean_text = re.sub(r"\d+[/-]\d+", "", clean_text)

        # (C) Remove textual date patterns (e.g., October 12, Oct 12)
        # (?i) ignores case
        clean_text = re.sub(r"(?i)(october|oct)\s*\d+", "", clean_text)

        # (D) Remove ordinal patterns (e.g., 12th)
        clean_text = re.sub(r"\d+(st|nd|rd|th)", "", clean_text)

        # 2. Verify Answer
        # Find '12' as an independent word in the remaining text (\b represents word boundary)
        target_pattern = rf"\b{self.correct_answer}\b"

        match = re.search(target_pattern, clean_text)

        if match:
            logger.info(f"Correct answer found: {answer}")
            return 1.0, "Success"
        else:
            # Traps like 12:00 or 10/12 have been removed above, so it falls here
            logger.info(f"Incorrect answer (filtered context): {answer}")
            return 0.0, f"Incorrect answer '{answer}', expected '{self.correct_answer}'"
