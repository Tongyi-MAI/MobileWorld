"""Technical debt triage task - parse complexity metrics and prioritize refactoring work."""

import re
import time

from mobile_world.runtime.app_helpers import mattermost
from mobile_world.runtime.app_helpers.mattermost import DEFAULT_PASSWORD, USERS
from mobile_world.runtime.app_helpers.system import (
    check_sms_via_adb,
    get_contacts_via_adb,
    time_sync_to_now,
)
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


def compute_complexity(cyclomatic: int, cognitive: int, loc: int) -> float:
    """Compute complexity score: cyclomatic × cognitive × (loc/100)."""
    return cyclomatic * cognitive * (loc / 100)


class MattermostTechnicalDebtTriageTask(BaseTask):
    """Analyze technical debt discussions with LaTeX complexity formulas and prioritize work."""

    task_tags = {"lang-en"}
    goal = (
        "Review the 'tech-debt-review' channel on Mattermost for technical debt discussions. "
        "Team members have posted complexity analysis using mathematical formulas. "
        "Your tasks:\n"
        "1. Identify the module with the HIGHEST complexity score (look for the LaTeX formula results).\n"
        "2. Send Sarah an SMS with the highest-priority module name and its complexity score.\n"
        "3. Create a new contact named 'Refactoring Team' with phone number '15559876543' "
        "and add the company 'TechDebt Solutions Inc'.\n"
        "4. Post a summary in the 'tech-debt-review' channel listing all modules sorted by "
        "complexity (highest first) in a markdown table format."
    )
    # Ground truth expected summary table:
    # | Module | Complexity Score |
    # |--------|------------------|
    # | PaymentProcessor | 47880.0 |
    # | AuthenticationService | 13440.0 |
    # | NotificationEngine | 8400.0 |
    # | ReportGenerator | 4180.0 |
    # | DataExporter | 2160.0 |
    snapshot_tag = "init_state"

    CHANNEL_NAME = "tech-debt-review"
    SARAH_PHONE = "14737474173"
    NEW_CONTACT_PHONE = "15559876543"
    NEW_CONTACT_NAME = "Refactoring Team"
    NEW_CONTACT_COMPANY = "TechDebt Solutions Inc"

    # Module complexity data - scores computed dynamically
    MODULES: dict[str, dict[str, int]] = {
        "PaymentProcessor": {"cyclomatic": 45, "cognitive": 38, "loc": 2800},
        "AuthenticationService": {"cyclomatic": 32, "cognitive": 28, "loc": 1500},
        "DataExporter": {"cyclomatic": 18, "cognitive": 15, "loc": 800},
        "NotificationEngine": {"cyclomatic": 28, "cognitive": 25, "loc": 1200},
        "ReportGenerator": {"cyclomatic": 22, "cognitive": 20, "loc": 950},
    }

    def __init__(self):
        super().__init__()
        # Compute scores dynamically
        self._module_scores: dict[str, float] = {}
        for name, data in self.MODULES.items():
            self._module_scores[name] = compute_complexity(
                data["cyclomatic"], data["cognitive"], data["loc"]
            )
        # Sort by score descending
        self._sorted_modules = sorted(self._module_scores.items(), key=lambda x: x[1], reverse=True)
        self._highest_module = self._sorted_modules[0][0]
        self._highest_score = self._sorted_modules[0][1]

    app_names = {"Mattermost", "Contacts", "Messages"}

    def _build_module_message(self, name: str) -> str:
        """Build a message for a module with computed complexity."""
        data = self.MODULES[name]
        cyc, cog, loc = data["cyclomatic"], data["cognitive"], data["loc"]
        score = compute_complexity(cyc, cog, loc)

        status_map = {
            "PaymentProcessor": "CRITICAL - Immediate refactoring needed!",
            "AuthenticationService": "High priority, needs decomposition.",
            "NotificationEngine": "Medium priority.",
            "ReportGenerator": "Medium-low priority.",
            "DataExporter": "Low priority, maintainable code.",
        }
        status = status_map.get(name, "Needs review.")

        warning = (
            "🚨\n\n**WARNING**: This module is extremely complex!\n\n" if score > 400 else "\n\n"
        )

        return (
            f"## {name} Module{warning}"
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Cyclomatic | {cyc} |\n"
            f"| Cognitive | {cog} |\n"
            f"| LOC | {loc} |\n\n"
            rf"Complexity: ${cyc} \times {cog} \times \frac{{{loc}}}{{100}} = {score}$"
            f"\n\n**Status**: {status}"
        )

    def initialize_task_hook(self, controller: AndroidController) -> bool:
        mattermost.start_mattermost_backend()
        time.sleep(5)

        cli = mattermost.MattermostCLI()
        cli.login(USERS["alex"], DEFAULT_PASSWORD)

        # Create tech-debt-review channel
        cli.create_channel(
            team=mattermost.TEAM_NAME,
            channel_name=self.CHANNEL_NAME,
            display_name="Tech Debt Review",
            private=False,
            purpose="Technical debt analysis and prioritization",
        )
        cli.add_users_to_channel(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            users=["harry.kong@neuralforge.ai", USERS["sofia"], USERS["mike"], USERS["sam"]],
        )

        # Introduction with complexity formula explanation
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message=(
                "# Technical Debt Complexity Analysis\n\n"
                "Team, I've completed the complexity analysis for our core modules. "
                "The complexity score formula is:\n\n"
                r"$\text{Score} = C_{cyclomatic} \times C_{cognitive} \times \frac{LOC}{100}$"
                "\n\nWhere:\n"
                r"- $C_{cyclomatic}$ = McCabe's cyclomatic complexity"
                "\n"
                r"- $C_{cognitive}$ = Cognitive complexity (SonarQube metric)"
                "\n"
                "- LOC = Lines of code\n\n"
                "Higher scores indicate higher refactoring priority."
            ),
        )

        # Sofia posts DataExporter analysis
        cli.logout()
        cli.login(USERS["sofia"], DEFAULT_PASSWORD)
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message=self._build_module_message("DataExporter"),
        )

        # Mike posts PaymentProcessor (highest complexity)
        cli.logout()
        cli.login(USERS["mike"], DEFAULT_PASSWORD)
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message=self._build_module_message("PaymentProcessor"),
        )

        # Discussion noise
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message="@alex Should we schedule a dedicated sprint for PaymentProcessor?",
        )

        # Alex posts AuthenticationService
        cli.logout()
        cli.login(USERS["alex"], DEFAULT_PASSWORD)
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message=self._build_module_message("AuthenticationService"),
        )
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message="@mike Yes, let's discuss in the planning meeting.",
        )

        # Sofia posts NotificationEngine
        cli.logout()
        cli.login(USERS["sofia"], DEFAULT_PASSWORD)
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message=self._build_module_message("NotificationEngine"),
        )

        # Sam posts ReportGenerator
        cli.logout()
        cli.login(USERS["sam"], DEFAULT_PASSWORD)
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message=self._build_module_message("ReportGenerator"),
        )

        # More noise
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message="Quick note: the formula can also include test coverage as a factor.",
        )

        cli.logout()
        cli.login(USERS["mike"], DEFAULT_PASSWORD)
        cli.send_message(
            team=mattermost.TEAM_NAME,
            channel=self.CHANNEL_NAME,
            message="Good point @sam. For v2 we should add that.",
        )

        if not time_sync_to_now():
            return False

        return True

    def _extract_table_rows(self, msg_content: str) -> list[tuple[str, float]]:
        """
        Extract module names and scores from a markdown table in the message.
        Returns list of (module_name, score) tuples in the order they appear.
        """
        rows: list[tuple[str, float]] = []
        lines = msg_content.split("\n")

        for line in lines:
            if "|" not in line or line.strip().startswith("|--") or line.strip().startswith("|-"):
                continue

            # Split by | and clean up
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) < 2:
                continue

            # Try to find module name and score
            for module_name in self.MODULES:
                if module_name.lower() in line.lower():
                    # Try to extract a number from the line (the score)
                    numbers = re.findall(r"(\d+\.?\d*)", line)
                    for num_str in numbers:
                        try:
                            num = float(num_str)
                            # Score should be > 10 (to filter out small numbers)
                            if num > 10:
                                rows.append((module_name, num))
                                break
                        except ValueError:
                            continue
                    break

        return rows

    def _verify_sort_order(self, rows: list[tuple[str, float]]) -> bool:
        """Verify that rows are sorted by score in descending order."""
        if len(rows) < 2:
            return False

        scores = [score for _, score in rows]
        # Check if scores are in descending order (with small tolerance for rounding)
        for i in range(len(scores) - 1):
            if scores[i] < scores[i + 1] - 0.1:  # Allow small tolerance
                return False
        return True

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        self._check_is_initialized()
        assert mattermost.is_mattermost_healthy()

        # Check 1: SMS sent to Sarah with correct content (module name + score)
        score_int = str(int(self._highest_score))
        score_str = str(self._highest_score)

        sms_sent = check_sms_via_adb(
            controller,
            self.SARAH_PHONE,
            [self._highest_module],
        )
        if not sms_sent:
            return (
                0.0,
                f"SMS not sent to Sarah ({self.SARAH_PHONE}) with {self._highest_module} info",
            )

        # Also verify score is mentioned (either integer or decimal form)
        sms_has_score = check_sms_via_adb(
            controller,
            self.SARAH_PHONE,
            [score_int],
        ) or check_sms_via_adb(
            controller,
            self.SARAH_PHONE,
            [score_str],
        )
        if not sms_has_score:
            return (
                0.0,
                f"SMS to Sarah missing complexity score ({self._highest_score})",
            )

        # Check 2: New contact created
        contacts = get_contacts_via_adb(controller, name=self.NEW_CONTACT_NAME)
        if not contacts:
            return 0.0, f"Contact '{self.NEW_CONTACT_NAME}' not created"

        contact_found = False
        for contact in contacts:
            phones = contact.get("phones", [])
            # Normalize to digits only so formatted variants like "1 (555) 987-6543" match.
            phone_numbers = [
                "".join(filter(str.isdigit, p.get("number", ""))) for p in phones
            ]
            org = contact.get("organization", "").lower()
            if any(self.NEW_CONTACT_PHONE in num for num in phone_numbers):
                if "techdebt" in org.replace(" ", "").lower() or "solutions" in org.lower():
                    contact_found = True
                    break
        if not contact_found:
            return (
                0.0,
                f"Contact not created correctly (phone: {self.NEW_CONTACT_PHONE}, "
                f"company: {self.NEW_CONTACT_COMPANY})",
            )

        # Check 3: Summary posted in channel with markdown table AND correct sort order
        channel_info = mattermost.get_channel_info(channel_name=self.CHANNEL_NAME)
        if not channel_info:
            return 0.0, f"Channel '{self.CHANNEL_NAME}' not found"

        messages = mattermost.get_latest_messages()[:15]
        channel_messages = [m for m in messages if m[5] == channel_info[0]]

        summary_found = False
        sort_order_correct = False

        for msg in channel_messages:
            msg_content = msg[8]
            msg_content_lower = msg_content.lower()

            # Must be a table (contains |) and have all module names
            if "|" not in msg_content:
                continue

            all_modules_present = all(
                module.lower() in msg_content_lower for module in self.MODULES
            )
            if not all_modules_present:
                continue

            summary_found = True

            # Extract table rows and verify sort order
            rows = self._extract_table_rows(msg_content)
            if len(rows) >= len(self.MODULES):
                sort_order_correct = self._verify_sort_order(rows)
                if sort_order_correct:
                    break

            # Alternative check: verify module names appear in correct order in text
            # (PaymentProcessor should appear before AuthenticationService, etc.)
            expected_order = [name for name, _ in self._sorted_modules]
            positions = []
            for module in expected_order:
                pos = msg_content_lower.find(module.lower())
                if pos >= 0:
                    positions.append(pos)
                else:
                    positions.append(float("inf"))

            # Check if positions are in ascending order (meaning correct sort)
            if all(positions[i] <= positions[i + 1] for i in range(len(positions) - 1)):
                sort_order_correct = True
                break

        if not summary_found:
            return 0.0, "Summary table not posted in channel (missing modules or table format)"

        if not sort_order_correct:
            expected_order_str = " > ".join(
                f"{name}({score:.1f})" for name, score in self._sorted_modules
            )
            return (
                0.0,
                f"Summary table not sorted correctly by complexity. Expected order: {expected_order_str}",
            )

        return 1.0

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        mattermost.stop_mattermost_backend()
        return True
