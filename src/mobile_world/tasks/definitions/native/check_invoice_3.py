import time
from pathlib import Path

from loguru import logger

from mobile_world.runtime.app_helpers.system import check_sms_via_adb, reset_chrome
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class CheckInvoiceTask3(BaseTask):
    """Read the invoice PDF and report Consulting Services vs Software Development hours difference via SMS."""

    goal = (
        "Read the invoice PDF file in the download directory. "
        "Send a SMS to Mia and report how many fewer hours does Consulting Services have than Software Development?"
    )

    # Correct answer: Consulting Services (150h) has 250 fewer hours than Software Development (400h)
    CORRECT_ANSWER = 250
    PDF_FILENAME = "invoice.pdf"

    # Mia's contact information (from check_candidate_ask_user_1.py)
    RECIPIENT_NAME = "Mia Scott"
    RECIPIENT_PHONE = "14058298746"

    task_tags = {"lang-en"}

    app_names = {"Docreader", "Files", "Messages"}

    def initialize_task_hook(self, controller: AndroidController) -> bool:
        """Initialize task by pushing the invoice PDF to the device."""

        self.relevant_information = "The Mia's phone number can be found in the Contacts app. "

        try:
            # Reset Chrome first
            reset_chrome(controller)

            # Get path to the PDF in assets directory
            root_path = Path(__file__).resolve().parent
            local_pdf_path = root_path / "assets" / self.PDF_FILENAME

            logger.info(f"Looking for PDF at: {local_pdf_path}")

            # Check if PDF exists
            if not local_pdf_path.exists():
                logger.error(f"PDF file not found: {local_pdf_path}")
                return False

            # Define remote path on device (in Download directory for easy access)
            remote_pdf_path = f"/sdcard/Download/{self.PDF_FILENAME}"

            logger.info(f"Pushing PDF: {self.PDF_FILENAME} to {remote_pdf_path}")

            # Push the PDF to device
            result = controller.push_file(str(local_pdf_path), remote_pdf_path)

            if not result.success:
                logger.error(f"Failed to push PDF to device: {result.error}")
                return False

            # Wait a moment for file to be written
            time.sleep(0.5)

            # Trigger media scanner to make the PDF visible in file managers
            logger.info(f"Triggering media scan for {self.PDF_FILENAME}")
            controller.refresh_media_scan(remote_pdf_path)

            # Store the remote path for potential cleanup
            self._remote_pdf_path = remote_pdf_path

            logger.info("Successfully pushed PDF to device")
            return True

        except Exception as e:
            logger.error(f"Initialize task failed: {e}")
            return False

    def is_successful(self, controller: AndroidController) -> tuple[float, str]:
        """
        Check if the task is successful.

        Validation criteria:
        1. SMS was sent to correct phone number (Mia: 14058298746)
        2. SMS content contains the correct answer (250)
        """
        self._check_is_initialized()

        logger.info(
            f"Checking for SMS to {self.RECIPIENT_PHONE} with content: {self.CORRECT_ANSWER}"
        )

        # Check if SMS with correct answer was sent to the recipient
        result = check_sms_via_adb(
            controller,
            phone_number=self.RECIPIENT_PHONE,
            content=str(self.CORRECT_ANSWER),
        )

        if result:
            return 1.0, "success"
        else:
            return (
                0.0,
                f"No SMS found to {self.RECIPIENT_NAME} ({self.RECIPIENT_PHONE}) with correct answer: {self.CORRECT_ANSWER}",
            )
