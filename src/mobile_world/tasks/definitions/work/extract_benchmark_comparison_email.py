"""Extract benchmark comparison from arXiv paper and send email."""

from mobile_world.runtime.app_helpers.mail import get_sent_email_info
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class ExtractBenchmarkComparisonEmailTask(BaseTask):
    """Extract benchmark comparison from arXiv paper and send email."""

    goal = (
        "I am checking some benchmark numbers for our paper.\n"
        "Please open the paper at: https://arxiv.org/pdf/2508.15144\n"
        "In this paper, locate the results on the **MMBench-GUI L1** test set.\n"
        "From that benchmark, extract the performance scores of uitars-72B and Claude-3.7\n"
        "Then determine:\n"
        "1) Whether uitars-72B performs better or worse than Claude-3.7 on MMBench-GUI L1.\n"
        "2) The absolute difference in their scores (uitars-72B minus Claude-3.7), keeping the same units as in the table.\n"
        "Summarize the result in **one concise sentence** in the following style:\n"
        '"On MMBench-GUI L1, uitars-72B performs [better/worse] than Claude-3.7 by X.X points." \n'
        "Replace [better/worse] and X.X with the correct comparison and numeric difference.\n"
        "Then send an email to my coauthor at coauthor@example.com with:\n"
        "- Subject: MMBench-GUI L1 comparison (uitars-72B vs Claude-3.7)\n"
        "- Body: exactly that one sentence, and no extra text.\n"
    )
    task_tags = {"agent-mcp", "lang-en"}

    EMAIL_ADDRESS = "coauthor@example.com"
    EMAIL_SUBJECT = "MMBench-GUI L1 comparison (uitars-72B vs Claude-3.7)"

    # Expected email body content (exact format)
    EXPECTED_BODY = "On MMBench-GUI L1, uitars-72B performs better than Claude-3.7 by 0.1 points."

    app_names = {"MCP-arXiv", "Mail", "Chrome"}

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

        # Check 3: Verify email body contains exactly one sentence matching expected format
        email_body = email.get("body", "").strip()

        # Normalize comparison (remove extra spaces, handle different whitespace)
        expected_normalized = " ".join(self.EXPECTED_BODY.split())
        actual_normalized = " ".join(email_body.split())

        if expected_normalized != actual_normalized:
            return (
                0.0,
                f"Email body mismatch. Expected: '{self.EXPECTED_BODY}', Got: '{email_body}'",
            )

        return 1.0

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        return True
