"""Visual instruction response task - execute system actions based on image content in chat."""

import time
from urllib.parse import quote

from mobile_world.runtime.app_helpers import mattermost
from mobile_world.runtime.app_helpers.mattermost import DEFAULT_PASSWORD, USERS
from mobile_world.runtime.app_helpers.system import (
    check_alarm_via_adb,
    get_contacts_via_adb,
    time_sync_to_now,
)
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class MattermostVisualInstructionResponseTask(BaseTask):
    """
    Task where the agent must extract information from images posted in Mattermost
    and execute actions in system apps (Contacts, Clock).
    """

    task_tags = {"lang-en"}
    goal = (
        "Check the 'emergency-response' channel on Mattermost. The operations manager "
        "has posted a whiteboard photo with emergency contacts and shift times. "
        "Please:\n"
        "1. Create new contacts for the people listed in the 'Emergency Contacts' image. Only fill the first name and phone number.\n"
        "2. Set alarms for the shift start times listed in the 'Shift Schedule' image, "
        "using the shift name as the alarm label."
    )
    snapshot_tag = "init_state"

    CHANNEL_NAME = "emergency-response"

    # Data to be embedded in images
    CONTACTS_DATA = [
        {"name": "Dr. Smith", "phone": "555-1010"},
        {"name": "Safety Officer", "phone": "555-2020"},
    ]

    ALARMS_DATA = [
        {"label": "Morning Shift", "time_str": "08:00 AM", "hour": 8, "minute": 0},
        {"label": "Evening Shift", "time_str": "08:00 PM", "hour": 20, "minute": 0},
    ]

    def __init__(self):
        super().__init__()

    app_names = {"Mattermost", "Contacts", "Clock"}

    def _generate_image_url(self, title: str, lines: list[str]) -> str:
        """Generate a placehold.co URL containing the text."""
        # placehold.co supports simple text. We use newlines %0A.
        full_text = f"{title}\n" + "\n".join(lines)
        encoded_text = quote(full_text)
        # Using a distinct color to make it look intentional
        return f"https://placehold.co/600x400/EEE/31343C/png?text={encoded_text}"

    def initialize_task_hook(self, controller: AndroidController) -> bool:
        mattermost.start_mattermost_backend()
        time.sleep(5)

        cli = mattermost.MattermostCLI()
        cli.login(USERS["alex"], DEFAULT_PASSWORD)

        cli.create_channel(
            team=mattermost.TEAM_NAME,
            channel_name=self.CHANNEL_NAME,
            display_name="Emergency Response",
            private=False,
            purpose="Coordination for emergency protocols",
        )
        cli.add_users_to_channel(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            users=["harry.kong@neuralforge.ai", USERS["sofia"]],
        )

        # 1. Post text context
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message=(
                "**URGENT UPDATE**\n\n"
                "The central server is down, so I'm posting the manual override details here. "
                "Please update your local devices immediately."
            ),
        )

        # 2. Post Contacts Image
        contact_lines = [f"{c['name']}: {c['phone']}" for c in self.CONTACTS_DATA]
        contacts_url = self._generate_image_url("EMERGENCY CONTACTS", contact_lines)

        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message=(
                f"Here is the updated contact list for the response team:\n\n"
                f"![Emergency Contacts]({contacts_url})"
            ),
        )

        # 3. Post Alarms Image
        alarm_lines = [f"{a['label']}: {a['time_str']}" for a in self.ALARMS_DATA]
        alarms_url = self._generate_image_url("SHIFT SCHEDULE", alarm_lines)

        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message=(
                f"And here are the mandatory check-in times for the manual shifts:\n\n"
                f"![Shift Schedule]({alarms_url})"
            ),
        )

        # 4. Add some noise/conversation
        cli.logout()
        cli.login(USERS["sofia"], DEFAULT_PASSWORD)
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message="Got it. Is the Safety Officer number reachable 24/7?",
        )

        cli.logout()
        cli.login(USERS["alex"], DEFAULT_PASSWORD)
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message="Yes, use that number for all critical incidents.",
        )

        if not time_sync_to_now():
            return False

        return True

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        self._check_is_initialized()

        # Check 1: Contacts created
        for contact_data in self.CONTACTS_DATA:
            name = contact_data["name"]
            expected_phone = contact_data["phone"]

            contacts = get_contacts_via_adb(controller, name=name)
            if not contacts:
                return 0.0, f"Contact '{name}' not found"

            # Verify phone number
            phone_found = False
            for contact in contacts:
                phones = contact.get("phones", [])
                # Normalize phones to digits only so formatted variants
                # (e.g. "1 (555) 987-6543", "+1 555-1010") match.
                phone_numbers = [
                    "".join(filter(str.isdigit, p.get("number", ""))) for p in phones
                ]
                clean_expected = "".join(filter(str.isdigit, expected_phone))

                if any(clean_expected in num for num in phone_numbers):
                    phone_found = True
                    break

            if not phone_found:
                return 0.0, f"Contact '{name}' found but phone number '{expected_phone}' is missing"

        # Check 2: Alarms set
        for alarm_data in self.ALARMS_DATA:
            hour = alarm_data["hour"]
            minute = alarm_data["minute"]
            label_part = alarm_data["label"]

            alarm = check_alarm_via_adb(controller, hour, minute)
            if not alarm:
                return 0.0, f"No alarm found set for {hour:02d}:{minute:02d}"

            if not alarm.get("enabled", False):
                return 0.0, f"Alarm for {hour:02d}:{minute:02d} exists but is not enabled"

            actual_label = alarm.get("label", "") or ""
            if label_part.lower() not in actual_label.lower():
                return (
                    0.0,
                    f"Alarm for {hour:02d}:{minute:02d} has incorrect label. Expected '{label_part}', got '{actual_label}'",
                )

        return 1.0

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        mattermost.stop_mattermost_backend()
        return True
