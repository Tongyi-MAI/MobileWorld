"""Mattermost email task implementation - send contract via email and create calendar event."""

import time

from mobile_world.runtime.app_helpers import mattermost
from mobile_world.runtime.app_helpers.system import enable_auto_time_sync
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class MattermostReadingGroupTask(BaseTask):
    task_tags = {"lang-en"}
    goal = "Please help me complete the task in mattermost reading group following sam's request."
    snapshot_tag = "init_state"
    PAPER_ID = "2511.21631"
    MMMU_PRO_SCORE = ["68.1", "69.3"]

    app_names = {"Mattermost", "Chrome"}

    def initialize_task_hook(self, controller: AndroidController) -> None:
        mattermost.start_mattermost_backend()
        time.sleep(5)
        cli = mattermost.MattermostCLI()
        cli.login(mattermost.SAM_ACCOUNT["username"], mattermost.SAM_ACCOUNT["password"])
        cli.create_channel(
            team=mattermost.TEAM_NAME,
            channel_name="reading",
            display_name="Reading Group",
            private=False,
            purpose="Reading group",
            header="Reading group",
        )
        cli.add_users_to_channel(
            team=mattermost.TEAM_NAME,
            channel="reading",
            users=["sam.oneill@neuralforge.ai", "harry.kong@neuralforge.ai"],
        )
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel="reading",
            message="Welcome to the reading group! For today's reading, please read the Qwen3-vl paper and share your thoughts @harry. Post here the arxiv link of the paper. Btw, what's their MMMU_Pro score for their best model?",
        )
        if not enable_auto_time_sync(controller):  # chrome needs auto time sync to work
            return False
        return True

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        self._check_is_initialized()
        assert mattermost.is_mattermost_healthy()

        channel_info = mattermost.get_channel_info(channel_name="reading")
        assert channel_info is not None

        messages = mattermost.get_latest_messages()[:5]
        paper_mentioned = False
        mmmu_pro_score_mentioned = False
        for message in messages:
            if message[5] != channel_info[0]:
                continue
            if self.PAPER_ID in message[8]:
                paper_mentioned = True
            for score in self.MMMU_PRO_SCORE:
                if score in message[8]:
                    mmmu_pro_score_mentioned = True
                    break
        if paper_mentioned and mmmu_pro_score_mentioned:
            return 1.0
        return 0.0, "Paper not mentioned or MMMU_Pro score not mentioned"

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        mattermost.stop_mattermost_backend()
