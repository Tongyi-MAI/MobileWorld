"""Extract data pipeline stages from arXiv paper and send email."""

from mobile_world.runtime.app_helpers.mail import get_sent_email_info
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class ExtractPipelineStagesEmailTask(BaseTask):
    """Extract data pipeline stages from arXiv paper and send email."""

    goal = (
        "I have just discussed with my collaborator, and they asked me to carefully review the\n"
        "data pipeline figure in the paper: https://arxiv.org/pdf/2505.09388.\n"
        "Please open this paper, locate the data pipeline figure, and focus on the\n"
        "upper part of the figure, which is divided into four stages.\n"
        "For each of these four stages, extract its step description in the figure.\n"
        "Format each line as:\n"
        "stage N: content\n"
        "Then send an email to chen@gmail.com with:\n"
        "- Subject: Data pipeline stages from 2505.09388\n"
        "- Body: exactly four lines, one for each stage, in the order stage 1 to stage N,\n"
        "  each following the format 'stage N: content' with no extra text.\n"
    )
    task_tags = {"agent-mcp", "lang-en"}

    EMAIL_ADDRESS = "chen@gmail.com"
    EMAIL_SUBJECT = "Data pipeline stages from 2505.09388"

    # Expected email body content (exact format)
    EXPECTED_BODY_LINES = [
        "stage 1: Long-CoT cold start",
        "stage 2: Reasoning RL",
        "stage 3: Thinking-mode fusion",
        "stage 4: General RL",
    ]

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

        # Check 3: Verify email body contains exactly 4 lines in correct order
        email_body = email.get("body", "").strip()
        body_lines = [line.strip() for line in email_body.split("\n") if line.strip()]

        if len(body_lines) != 4:
            return (
                0.0,
                f"Email body should have exactly 4 lines, found {len(body_lines)}: {body_lines}",
            )

        # Check each line matches expected format
        for i, (expected_line, actual_line) in enumerate(zip(self.EXPECTED_BODY_LINES, body_lines)):
            # Normalize comparison (remove extra spaces, handle different whitespace)
            expected_normalized = " ".join(expected_line.split())
            actual_normalized = " ".join(actual_line.split())

            if expected_normalized != actual_normalized:
                return (
                    0.0,
                    f"Line {i + 1} mismatch. Expected: '{expected_line}', Got: '{actual_line}'",
                )

        return 1.0

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        return True
