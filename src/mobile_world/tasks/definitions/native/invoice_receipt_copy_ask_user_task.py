"""Invoice/Receipt copy task - find invoice/receipt PDFs from this month and copy to Finance folder."""

import datetime
import os
import random
import re
import tempfile
from typing import Any

from loguru import logger

from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import execute_adb
from mobile_world.tasks.base import BaseTask


class InvoiceReceiptCopyAskUserTask(BaseTask):
    """Find invoice/receipt PDFs from this month and copy to Finance folder."""

    goal = "在Download里找到11月内文件名包含invoice或者receipt的PDF复制进我专门用来收录发票和收据的文件夹。"

    TARGET_STORAGE_FOLDER = "Documents/expense/invoice"

    # Fixed invoice/receipt content items (10 items)
    INVOICE_ITEMS = [
        {
            "item": "Office Supplies",
            "date": "2025-01-15",
            "amount": "125.50",
            "description": "Printer paper, pens, notebooks",
            "reimbursable": "Yes",
        },
        {
            "item": "Software License",
            "date": "2025-01-20",
            "amount": "299.99",
            "description": "Annual subscription for design software",
            "reimbursable": "Yes",
        },
        {
            "item": "Travel Expense",
            "date": "2025-01-25",
            "amount": "450.00",
            "description": "Flight ticket for business trip",
            "reimbursable": "Yes",
        },
        {
            "item": "Meal Expense",
            "date": "2025-02-01",
            "amount": "85.30",
            "description": "Business lunch with client",
            "reimbursable": "Yes",
        },
        {
            "item": "Equipment Purchase",
            "date": "2025-02-05",
            "amount": "1200.00",
            "description": "New laptop for development team",
            "reimbursable": "No",
        },
        {
            "item": "Internet Service",
            "date": "2025-02-10",
            "amount": "79.99",
            "description": "Monthly internet bill",
            "reimbursable": "No",
        },
        {
            "item": "Conference Registration",
            "date": "2025-02-15",
            "amount": "350.00",
            "description": "Tech conference registration fee",
            "reimbursable": "Yes",
        },
        {
            "item": "Hotel Accommodation",
            "date": "2025-02-20",
            "amount": "280.00",
            "description": "Hotel stay for conference",
            "reimbursable": "Yes",
        },
        {
            "item": "Taxi Fare",
            "date": "2025-02-22",
            "amount": "45.50",
            "description": "Taxi to airport",
            "reimbursable": "Yes",
        },
        {
            "item": "Training Course",
            "date": "2025-02-25",
            "amount": "550.00",
            "description": "Online training course for team",
            "reimbursable": "No",
        },
    ]

    task_tags = {"lang-cn"}

    def __init__(self, params: dict[str, Any] = None):
        super().__init__(params)
        self.invoice_files_created = []  # invoice/receipt PDF files that should be copied
        self.other_files_created = []  # Other files (should not be copied)
        self.current_month = datetime.datetime.now().month
        self.current_year = datetime.datetime.now().year

    def reset_task_state(self) -> None:
        self.invoice_files_created = []
        self.other_files_created = []

    app_names = {
        "Files",
    }

    def _generate_invoice_content(self, items: list[dict]) -> str:
        """Generate invoice/receipt content from selected items."""
        content = "INVOICE/RECEIPT\n"
        content += "=" * 50 + "\n\n"

        total_amount = 0.0
        for item in items:
            content += f"Item: {item['item']}\n"
            content += f"Date: {item['date']}\n"
            content += f"Amount: ${item['amount']}\n"
            content += f"Description: {item['description']}\n"
            content += f"Reimbursable: {item['reimbursable']}\n"
            content += "-" * 50 + "\n"
            total_amount += float(item["amount"])

        content += f"\nTotal Amount: ${total_amount:.2f}\n"
        content += "=" * 50 + "\n"

        return content

    def initialize_task_hook(self, controller: AndroidController) -> None:
        """Create test invoice/receipt PDF files in Download directory."""

        self.relevant_information = f"My folder for collecting invoices and receipts is {self.TARGET_STORAGE_FOLDER}. If it not exists, you should create it first."

        download_path = "/sdcard/Download"
        finance_path = "/sdcard/Finance"

        logger.info("Cleaning up existing files in Download directory...")
        execute_adb(f"shell rm -rf {download_path}/*")  # Clean up existing files

        # Create Finance folder (should exist, but create if not)
        execute_adb(f"shell mkdir -p {finance_path}")

        logger.info("Creating test invoice/receipt files in Download...")

        today = datetime.datetime.now()
        temp_dir = tempfile.mkdtemp()
        failed_files = []

        # File names for invoice/receipt files
        invoice_file_names = ["invoice_2025_001.pdf", "invoice_payment.pdf", "receipt_2025_002.pdf"]

        # Set dates: 1 file in November 2025, 2 files outside November
        # invoice_2025_001.pdf: November 15, 2025
        # invoice_payment.pdf: October 20, 2025 (outside November)
        # receipt_2025_002.pdf: December 5, 2025 (outside November)
        file_dates = [
            datetime.datetime(2025, 11, 15, 12, 0),  # November
            datetime.datetime(2025, 10, 20, 12, 0),  # October
            datetime.datetime(2025, 12, 5, 12, 0),  # December
        ]

        try:
            for i, filename in enumerate(invoice_file_names):
                date = file_dates[i]
                days_ago = (today - date).days

                # Randomly select 1-3 items from INVOICE_ITEMS
                num_items = random.randint(1, 3)
                selected_items = random.sample(self.INVOICE_ITEMS, num_items)

                # Generate content
                content = self._generate_invoice_content(selected_items)

                # Create local file
                filepath = os.path.join(temp_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("%PDF-1.4\n")
                    f.write(content)

                # Push to Android
                remote_path = f"{download_path}/{filename}"
                result = execute_adb(f"push {filepath} {remote_path}")

                if result.success:
                    # Set file creation/modification time using Unix timestamp
                    # Convert datetime to Unix timestamp
                    unix_timestamp = int(date.timestamp())
                    # Use touch with -d option and @ prefix for Unix timestamp
                    touch_result = execute_adb(f"shell touch -d @{unix_timestamp} {remote_path}")

                    if not touch_result.success:
                        logger.warning(
                            f"Failed to set timestamp for {filename}: {touch_result.error}"
                        )
                        # Try alternative format as fallback
                        timestamp_str = date.strftime("%m%d%H%M%Y")  # MMDDhhmmYYYY format
                        touch_result = execute_adb(f"shell touch -t {timestamp_str} {remote_path}")
                        if not touch_result.success:
                            logger.warning(
                                f"Failed to set timestamp with fallback method: {touch_result.error}"
                            )

                    is_this_month = date.year == 2025 and date.month == 11
                    self.invoice_files_created.append(
                        {
                            "filename": filename,
                            "days_ago": days_ago,
                            "date": date,
                            "is_this_month": is_this_month,
                            "items": selected_items,
                        }
                    )

                    status = "- November" if is_this_month else "- Not November"
                    logger.info(
                        f"Created invoice/receipt file: {filename} ({date.strftime('%Y-%m-%d')}) [{status}]"
                    )
                else:
                    failed_files.append(filename)
                    logger.error(f"Failed to create {filename}: {result.error}")

            # Create 6 other files (not invoice/receipt) to test filtering
            other_file_names = [
                "report_2025.pdf",
                "document.txt",
                "presentation.pdf",
                "notes.doc",
                "data.csv",
                "summary.pdf",
            ]

            for filename in other_file_names:
                content = f"This is a {filename.split('.')[-1]} file, not an invoice or receipt.\n"

                # Create local file
                filepath = os.path.join(temp_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)

                # Push to Android
                remote_path = f"{download_path}/{filename}"
                result = execute_adb(f"push {filepath} {remote_path}")

                if result.success:
                    self.other_files_created.append({"filename": filename, "path": remote_path})
                    logger.info(f"Created other file: {filename}")
                else:
                    failed_files.append(filename)
                    logger.error(f"Failed to create {filename}: {result.error}")

        finally:
            # Clean up temp directory
            for file in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, file))
            os.rmdir(temp_dir)

        if failed_files:
            logger.warning(f"Failed to create {len(failed_files)} files: {failed_files}")
            if len(failed_files) > 2:
                raise RuntimeError(
                    f"Failed to create {len(failed_files)} files. Task initialization failed."
                )

        # Filter files that should be copied (November 2025)
        files_to_copy = [f for f in self.invoice_files_created if f["is_this_month"]]

        logger.info(f"\n{'=' * 60}")
        logger.info(
            f"Total files created: {len(self.invoice_files_created) + len(self.other_files_created)}"
        )
        logger.info(f"  - Invoice/receipt files: {len(self.invoice_files_created)}")
        logger.info(f"    * November (to be copied): {len(files_to_copy)}")
        logger.info(
            f"    * Not November (should not be copied): {len(self.invoice_files_created) - len(files_to_copy)}"
        )
        logger.info(f"  - Other files (should not be copied): {len(self.other_files_created)}")
        logger.info("\nFiles to be copied to Finance/invoice/:")
        for file in files_to_copy:
            logger.info(f"  - {file['filename']} ({file['date'].strftime('%Y-%m-%d')})")
        logger.info(f"{'=' * 60}")

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        """
        Check if the task is successful.

        Validation criteria (all must pass to get score 1.0):
        1. Target folder Documents/expense/invoice exists
        2. Selected files are from November 2025
        3. Files are copied to Documents/expense/invoice folder
        4. Files in folder match expected count and names
        5. All files match invoice/receipt pattern
        """
        self._check_is_initialized()

        # Use TARGET_STORAGE_FOLDER from class definition
        expected_folder_path = f"/sdcard/{self.TARGET_STORAGE_FOLDER}"

        # Files that should be copied (November 2025)
        expected_files = [f for f in self.invoice_files_created if f["is_this_month"]]
        expected_filenames = [f["filename"] for f in expected_files]

        logger.info(f"Expected folder: {expected_folder_path}")
        logger.info(f"Expected files to copy: {expected_filenames}")

        # ===== CHECK 1: Verify target folder exists =====
        result = execute_adb(f"shell ls -d {expected_folder_path}")
        if not result.success:
            return 0.0, f"Target folder '{self.TARGET_STORAGE_FOLDER}' does not exist"

        # ===== CHECK 2: Verify files in target folder =====
        result = execute_adb(f"shell ls {expected_folder_path}")
        if not result.success:
            return 0.0, f"Failed to list files in {expected_folder_path}: {result.error}"

        files_in_folder = [f.strip() for f in result.output.strip().split("\n") if f.strip()]

        logger.info(f"Files in {expected_folder_path}: {files_in_folder}")

        # ===== CHECK 3: Verify file count is correct =====
        if len(files_in_folder) != len(expected_filenames):
            return 0.0, (
                f"Expected {len(expected_filenames)} files in folder, found {len(files_in_folder)}. "
                f"Expected: {expected_filenames}, Found: {files_in_folder}"
            )

        # ===== CHECK 4: Verify all expected files are in folder =====
        missing_files = set(expected_filenames) - set(files_in_folder)
        if missing_files:
            return 0.0, f"Missing files in folder: {missing_files}. Found: {files_in_folder}"

        # ===== CHECK 5: Verify no extra files in folder =====
        extra_files = set(files_in_folder) - set(expected_filenames)
        if extra_files:
            return (
                0.0,
                f"Unexpected files in folder: {extra_files}. Expected: {expected_filenames}",
            )

        # ===== CHECK 6: Verify selected files are from November 2025 =====
        # Check original file timestamps in Download directory to ensure they are from November 2025
        # (Copied files will have current timestamp, so we need to check the original files)
        download_path = "/sdcard/Download"
        for filename in files_in_folder:
            original_file_path = f"{download_path}/{filename}"

            # Get file modification time from original file in Download
            result = execute_adb(f"shell stat -c %Y {original_file_path}")

            if result.success:
                try:
                    file_timestamp = int(result.output.strip())
                    file_date = datetime.datetime.fromtimestamp(file_timestamp)

                    # Check if file is from November 2025
                    if file_date.year != 2025 or file_date.month != 11:
                        return 0.0, (
                            f"File {filename} is from {file_date.strftime('%Y-%m')} (not November 2025). "
                            f"Only files from November 2025 should be copied."
                        )
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse timestamp for {filename}")
            else:
                logger.warning(
                    f"Could not get timestamp for original file {filename}: {result.error}"
                )

        # ===== CHECK 7: Verify files match invoice/receipt pattern =====
        # Check that all files in folder match invoice or receipt pattern
        invoice_pattern = re.compile(r".*invoice.*\.pdf$", re.IGNORECASE)
        receipt_pattern = re.compile(r".*receipt.*\.pdf$", re.IGNORECASE)

        for filename in files_in_folder:
            if not (invoice_pattern.match(filename) or receipt_pattern.match(filename)):
                return 0.0, f"File {filename} does not match invoice or receipt pattern"

        return 1.0, "success"
