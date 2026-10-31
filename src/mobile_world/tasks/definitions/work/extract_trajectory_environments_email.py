"""Extract trajectory data collection environments from arXiv paper and send email."""

from mobile_world.runtime.app_helpers.mail import get_sent_email_info
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class ExtractTrajectoryEnvironmentsEmailTask(BaseTask):
    """Extract trajectory data collection environments from arXiv paper and send email."""

    goal = (
        "Please open the paper at: https://arxiv.org/pdf/2508.15144\n"
        "My collaborator asked me to study how this paper collects trajectory data.\n"
        "Please locate the section(s) that describe the trajectory data collection process\n"
        "and identify in how many different environments they collect trajectories, and what these environments are.\n"
        "Summarize the answer in the following format:\n"
        "- The total number of environments: X\n"
        "- <name> \n"
        "- <name> \n"
        "- ... (and so on for all environments)\n"
        "Then send an email to my collaborator at collaborator@example.com with:\n"
        "- Subject: Trajectory data collection environments from 2508.15144\n"
        "- Body: the summary in the specified format\n"
    )
    task_tags = {"agent-mcp", "lang-en"}

    EMAIL_ADDRESS = "collaborator@example.com"
    EMAIL_SUBJECT = "Trajectory data collection environments from 2508.15144"

    # Expected environments (order doesn't matter for validation)
    EXPECTED_ENVIRONMENTS = {"PC", "Mobile", "Web"}
    EXPECTED_TOTAL_COUNT = 3

    app_names = {"MCP-arXiv", "Mail"}

    def initialize_task_hook(self, controller: AndroidController) -> bool:
        return True

    async def is_successful_async(self, controller: AndroidController) -> float | tuple[float, str]:
        """Check if the task is successful."""
        self._check_is_initialized()

        email = get_sent_email_info()
        if email is None:
            return 0.0, "No email sent"

        # Check 1: Verify email recipient
        if email.get("to", "").lower() != self.EMAIL_ADDRESS.lower():
            return (
                0.0,
                f"Email sent to wrong address: {email.get('to')} (expected: {self.EMAIL_ADDRESS})",
            )

        # Check 2: Verify email subject
        email_subject = email.get("subject", "").strip()
        if email_subject != self.EMAIL_SUBJECT:
            return (
                0.0,
                f"Email subject mismatch. Expected: '{self.EMAIL_SUBJECT}', Got: '{email_subject}'",
            )

        # Check 3: Verify email body contains environment information
        email_body = email.get("body", "").strip()

        # Check for total number of environments
        if f"total number of environments: {self.EXPECTED_TOTAL_COUNT}" not in email_body.lower():
            # Try alternative formats
            if (
                f"total number: {self.EXPECTED_TOTAL_COUNT}" not in email_body.lower()
                and f"number of environments: {self.EXPECTED_TOTAL_COUNT}" not in email_body.lower()
            ):
                return (
                    0.0,
                    f"Total number of environments ({self.EXPECTED_TOTAL_COUNT}) not found in email body",
                )

        # Extract environment names from email body (case-insensitive)
        found_environments = set()
        email_body_lower = email_body.lower()

        for env in self.EXPECTED_ENVIRONMENTS:
            # Check if environment name appears in email body (case-insensitive)
            if env.lower() in email_body_lower:
                found_environments.add(env)

        # Verify all expected environments are found
        if found_environments != self.EXPECTED_ENVIRONMENTS:
            missing = self.EXPECTED_ENVIRONMENTS - found_environments
            return (
                0.0,
                f"Missing environments in email body: {missing}. Found: {found_environments}",
            )

        return 1.0

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        return True
