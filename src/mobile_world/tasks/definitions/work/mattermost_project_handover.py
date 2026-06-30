"""Mattermost email task implementation - send contract via email and create calendar event."""

import re

from mobile_world.runtime.app_helpers import mattermost
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class MattermostProjectHandoverTask(BaseTask):
    """Mattermost project handover task - handle project handover via Mattermost."""

    goal = "I'm passing the Phoenix project to Alex. Add Alex to the phoenix channel on mattermost.  ping everyone to schedule a 1-hour project meeting on Monday (find an available time slot from my calendar). Use this exact format in your message: `Meeting Time: [YYYY-MM-DD] from [HH:MM] to [HH:MM]`"
    snapshot_tag = "init_state"

    task_tags = {"lang-en"}

    app_names = {"Mattermost", "Calendar"}

    def initialize_task_hook(self, controller: AndroidController) -> None:
        mattermost.start_mattermost_backend()

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        self._check_is_initialized()
        # to check if the task is successful, we need the mattermost backend to be running
        assert mattermost.is_mattermost_healthy()

        # check alex has been added to the phoenix channel
        alex_added = mattermost.is_user_in_channel(
            mattermost.ALEX_ID, mattermost.PHOENIX_CHANNEL_ID
        )
        if not alex_added:
            return 0.0, "Alex has not been added to the phoenix channel"
        message = mattermost.get_latest_messages()[0]
        if message[4] != mattermost.HARRY_ID or message[5] != mattermost.PHOENIX_CHANNEL_ID:
            return 0.0, "Last message is not sent to harry in the phoenix channel"
        pattern = r"Meeting Time:\s*(\d{4}-\d{2}-\d{2})\s+from\s+(\d{2}:\d{2})\s+to\s+(\d{2}:\d{2})"
        match = re.search(pattern, message[8], re.IGNORECASE)
        if not match:
            return 0.0, "Last message does not contain the meeting time"
        date_str = match.group(1).strip()
        start_time = match.group(2).strip()
        end_time = match.group(3).strip()

        # Check if it matches the expected values
        expected_date = "2025-10-20"
        expected_start = "11:00"
        expected_end = "12:00"

        if not (
            date_str == expected_date and start_time == expected_start and end_time == expected_end
        ):
            return 0.0, "Meeting time is not correct"
        return 1.0

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        mattermost.stop_mattermost_backend()
