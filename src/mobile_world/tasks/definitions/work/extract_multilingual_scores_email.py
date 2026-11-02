"""Extract multilingual evaluation scores from arXiv paper and send email."""

from mobile_world.runtime.app_helpers.mail import get_sent_email_info
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class ExtractMultilingualScoresEmailTask(BaseTask):
    """Extract multilingual evaluation scores from arXiv paper and send email."""

    goal = (
        "I am preparing the multilingual evaluation section of my paper.\n"
        "\n"
        "Please open the paper at: https://arxiv.org/pdf/2505.09388\n"
        "In this paper, the Multilingual Tasks results are presented in a table where the columns\n"
        'correspond to the two models "DeepSeek-V3 base" and "Qwen3-235B-A22B base",\n'
        "and each row corresponds to a benchmark such as MGSM, MMMLU, and INCLUDE.\n"
        "From this table, extract the scores of these two models on the following three benchmarks:\n"
        "- MGSM\n"
        "- MMMLU\n"
        "- INCLUDE\n"
        "\n"
        "Format the results so that each line corresponds to one benchmark, with the pattern:\n"
        "Benchmark: DeepSeek-V3 base=xx.xx, Qwen3-235B-A22B base=yy.yy\n"
        "For example:\n"
        "MGSM: DeepSeek-V3 base=82.68, Qwen3-235B-A22B base=83.53\n"
        "\n"
        "Then send an email to my advisor at advisor@example.com with:\n"
        "- Subject: Baseline comparison table from 2403.15137\n"
        "- Body: exactly three lines, in this order: MGSM, MMMLU, INCLUDE,\n"
        "each line following the specified format, and no extra text.\n"
    )
    task_tags = {"agent-mcp", "lang-en"}

    ARXIV_URL = "https://arxiv.org/pdf/2505.09388"
    EMAIL_ADDRESS = "advisor@example.com"
    EMAIL_SUBJECT = "Baseline comparison table from 2403.15137"

    # Expected email body content (exact format)
    EXPECTED_BODY_LINES = [
        "MGSM: DeepSeek-V3 base=82.68, Qwen3-235B-A22B base=83.53",
        "MMMLU: DeepSeek-V3 base=85.88, Qwen3-235B-A22B base=86.70",
        "INCLUDE: DeepSeek-V3 base=75.17, Qwen3-235B-A22B base=73.46",
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

        # Check 3: Verify email body contains exactly 3 lines in correct order
        email_body = email.get("body", "").strip()
        body_lines = [line.strip() for line in email_body.split("\n") if line.strip()]

        if len(body_lines) != 3:
            return (
                0.0,
                f"Email body should have exactly 3 lines, found {len(body_lines)}: {body_lines}",
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
