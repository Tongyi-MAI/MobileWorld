"""CV email task - find recent CV files and send via email."""

import datetime
import os
import random
import re
import tempfile
from typing import Any

from loguru import logger

from mobile_world.runtime.app_helpers import mail
from mobile_world.runtime.app_helpers.system import (
    time_sync_to_now,
)
from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import execute_adb
from mobile_world.tasks.base import BaseTask


class CVEmailTask(BaseTask):
    """Find recent CV files and send via email."""

    goal = "在Download内找到最近一个月下载的简历文件，把文件发送给HR_chen@gmail.com，标题为candidates_cv。"

    # Random names for CV files
    FIRST_NAMES = [
        "John",
        "Sarah",
        "Michael",
        "Emily",
        "David",
        "Jessica",
        "James",
        "Amanda",
        "Robert",
        "Lisa",
        "William",
        "Jennifer",
        "Richard",
        "Michelle",
        "Joseph",
        "Ashley",
        "Thomas",
        "Melissa",
        "Charles",
        "Nicole",
        "Christopher",
        "Stephanie",
        "Daniel",
        "Amy",
        "Matthew",
        "Angela",
        "Anthony",
        "Brenda",
        "Mark",
        "Emma",
        "Donald",
        "Olivia",
    ]

    LAST_NAMES = [
        "Smith",
        "Johnson",
        "Williams",
        "Brown",
        "Jones",
        "Garcia",
        "Miller",
        "Davis",
        "Rodriguez",
        "Martinez",
        "Hernandez",
        "Lopez",
        "Wilson",
        "Anderson",
        "Thomas",
        "Taylor",
        "Moore",
        "Jackson",
        "Martin",
        "Lee",
        "Thompson",
        "White",
        "Harris",
        "Sanchez",
        "Clark",
        "Ramirez",
        "Lewis",
        "Robinson",
        "Walker",
        "Young",
        "Allen",
        "King",
    ]

    EMAIL_ADDRESS = "HR_chen@gmail.com"
    EMAIL_SUBJECT = "candidates_cv"

    task_tags = {"lang-cn"}

    def __init__(self, params: dict[str, Any] = None):
        super().__init__(params)
        self.cv_files_created = []  # CV files that should be found and sent
        self.recipe_files_created = []  # Recipe files (should not be sent)

    def reset_task_state(self) -> None:
        self.cv_files_created = []
        self.recipe_files_created = []

    app_names = {"Files", "Mail"}

    def initialize_task_hook(self, controller: AndroidController) -> None:
        """Create test CV and recipe PDF files in Download directory."""

        download_path = "/sdcard/Download"
        today = datetime.datetime.now()

        logger.info("Creating CV and recipe PDF files in Download directory...")

        # Clean up any existing *_CV.pdf files to avoid interference
        result = execute_adb(f"shell ls {download_path}/*_CV.pdf")
        if result.success and result.output.strip():
            logger.info("Cleaning up existing *_CV.pdf files...")
            execute_adb(f"shell rm {download_path}/*_CV.pdf")

        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        failed_files = []

        time_sync_to_now()

        try:
            # Create 3 CV files (within last month)
            # Dates: 25, 15, 5 days ago (all within 30 days)
            cv_days_ago = [25, 15, 5]

            for days_ago in cv_days_ago:
                # Generate random name
                first_name = random.choice(self.FIRST_NAMES)
                last_name = random.choice(self.LAST_NAMES)
                name = f"{first_name}_{last_name}"

                date = today - datetime.timedelta(days=days_ago)
                filename = f"{name}_CV.pdf"

                # CV content
                content = f"""RESUME - {first_name} {last_name}

Contact Information:
Email: {first_name.lower()}.{last_name.lower()}@email.com
Phone: +1-555-{random.randint(1000, 9999)}
Address: {random.randint(100, 9999)} Main Street, City, State {random.randint(10000, 99999)}

Professional Summary:
Experienced professional with expertise in software development,
project management, and team leadership. Strong background in
technology and business operations.

Work Experience:
- Senior Software Engineer (2020-Present)
  Company: Tech Solutions Inc.
  Responsibilities:
  * Led development of mobile applications
  * Managed cross-functional teams
  * Implemented agile methodologies

- Software Developer (2017-2020)
  Company: Digital Innovations LLC
  Responsibilities:
  * Developed web applications
  * Collaborated with design teams
  * Maintained code quality standards

Education:
- Master of Science in Computer Science
  University: State University
  Year: 2017

- Bachelor of Science in Information Technology
  University: City College
  Year: 2015

Skills:
- Programming Languages: Python, Java, JavaScript
- Frameworks: React, Node.js, Django
- Tools: Git, Docker, Kubernetes
- Certifications: AWS Certified Developer

Download Date: {date.strftime("%Y-%m-%d")}
"""

                # Create local file
                filepath = os.path.join(temp_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("%PDF-1.4\n")
                    f.write(content)

                # Push to Android
                remote_path = f"{download_path}/{filename}"
                result = execute_adb(f"push {filepath} {remote_path}")

                if result.success:
                    # Set file creation/modification time (within last month)
                    timestamp_str = date.strftime("%Y%m%d%H%M")
                    touch_result = execute_adb(f"shell touch -t {timestamp_str} {remote_path}")

                    if not touch_result.success:
                        logger.warning(
                            f"Failed to set timestamp for {filename}: {touch_result.error}. File will have current timestamp."
                        )

                    self.cv_files_created.append(
                        {
                            "filename": filename,
                            "name": name,
                            "days_ago": days_ago,
                            "date": date,
                            "expected_timestamp": int(date.timestamp()),
                        }
                    )

                    logger.info(f"Created CV file: {filename} ({days_ago} days ago)")
                else:
                    failed_files.append(filename)
                    logger.error(f"Failed to create {filename}: {result.error}")

            # Create 7 recipe files (some within last month, some older)
            # Mix of dates: some within month, some older
            recipe_days_ago = [20, 10, 3, 35, 40, 50, 60]

            recipe_titles = [
                "Chocolate_Chip_Cookies",
                "Spaghetti_Carbonara",
                "Chicken_Stir_Fry",
                "Beef_Stew",
                "Caesar_Salad",
                "Fish_Tacos",
                "Vegetable_Curry",
            ]

            for days_ago, title in zip(recipe_days_ago, recipe_titles):
                date = today - datetime.timedelta(days=days_ago)
                filename = f"{title}_Recipe.pdf"

                # Recipe content
                content = f"""Recipe: {title.replace("_", " ")}

Ingredients:
- Main ingredient
- Spices and seasonings
- Vegetables
- Cooking oil

Instructions:
1. Prepare ingredients
2. Heat pan
3. Cook main ingredient
4. Add vegetables
5. Season to taste
6. Serve hot

Cooking Time: 30 minutes
Serves: 4 people

Download Date: {date.strftime("%Y-%m-%d")}
"""

                # Create local file
                filepath = os.path.join(temp_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("%PDF-1.4\n")
                    f.write(content)

                # Push to Android
                remote_path = f"{download_path}/{filename}"
                result = execute_adb(f"push {filepath} {remote_path}")

                if result.success:
                    # Set file creation/modification time
                    timestamp_str = date.strftime("%Y%m%d%H%M")
                    touch_result = execute_adb(f"shell touch -t {timestamp_str} {remote_path}")

                    if not touch_result.success:
                        logger.warning(
                            f"Failed to set timestamp for {filename}: {touch_result.error}. File will have current timestamp."
                        )

                    self.recipe_files_created.append(
                        {
                            "filename": filename,
                            "days_ago": days_ago,
                            "within_month": days_ago <= 30,
                            "date": date,
                        }
                    )

                    within_marker = "- Within month" if days_ago <= 30 else "- Older than month"
                    logger.info(
                        f"Created recipe file: {filename} ({days_ago} days ago) [{within_marker}]"
                    )
                else:
                    failed_files.append(filename)
                    logger.error(f"Failed to create {filename}: {result.error}")

        finally:
            # Clean up temp directory
            for file in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, file))
            os.rmdir(temp_dir)

        # Check if too many files failed to create
        if failed_files:
            logger.warning(f"Failed to create {len(failed_files)} files: {failed_files}")
            if len(failed_files) > 3:
                raise RuntimeError(
                    f"Failed to create {len(failed_files)} files. Task initialization failed."
                )

        logger.info(f"\n{'=' * 60}")
        logger.info(
            f"Total files created: {len(self.cv_files_created) + len(self.recipe_files_created)}"
        )
        logger.info(f"  - CV files (to be sent): {len(self.cv_files_created)}")
        logger.info(f"  - Recipe files (should not be sent): {len(self.recipe_files_created)}")
        logger.info("\nCV files to be found and sent:")
        for cv_file in self.cv_files_created:
            logger.info(f"  - {cv_file['filename']} ({cv_file['days_ago']} days ago)")
        logger.info(f"{'=' * 60}")

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        """
        Check if the task is successful.

        Validation criteria (all must pass to get score 1.0):
        1. All 3 CV files are found and attached to email
        2. No extra files (non-CV files) are attached
        3. Email is sent to HR_chen@gmail.com
        4. Email subject is "candidates_cv"
        """
        self._check_is_initialized()

        # ===== CHECK 1: Email was sent =====
        sent_email_info = mail.get_sent_email_info()

        if sent_email_info is None:
            return 0.0, "No email sent"

        # ===== CHECK 2: Email sent to correct address =====
        if sent_email_info.get("to") != self.EMAIL_ADDRESS:
            return (
                0.0,
                f"Email sent to wrong address: {sent_email_info.get('to')} (expected: {self.EMAIL_ADDRESS})",
            )

        # ===== CHECK 3: Email subject is correct =====
        subject = sent_email_info.get("subject", "")
        if subject != self.EMAIL_SUBJECT:
            return (
                0.0,
                f"Email subject is incorrect: '{subject}' (expected: '{self.EMAIL_SUBJECT}')",
            )

        # ===== CHECK 4: Check attachments =====
        # Get attachments from email info
        # Attachments might be list of strings or list of objects with "name" field
        attachments_raw = sent_email_info.get("attachments", [])

        if not attachments_raw:
            return 0.0, "Email has no attachments"

        # Normalize attachments to list of filenames
        attachments = []
        for att in attachments_raw:
            if isinstance(att, dict):
                # Object format: {"name": "filename.pdf"}
                if "name" in att:
                    attachments.append(att["name"])
                else:
                    # Try other possible keys
                    for key in ["filename", "file", "path"]:
                        if key in att:
                            attachments.append(att[key])
                            break
            elif isinstance(att, str):
                # String format: "filename.pdf" or "/path/to/filename.pdf"
                attachments.append(att)

        if not attachments:
            return 0.0, f"Could not parse attachments from email info: {attachments_raw}"

        logger.info(f"Email attachments: {attachments}")

        # ===== CHECK 5: All 3 CV files are attached =====
        cv_filenames = [f["filename"] for f in self.cv_files_created]

        missing_cv_files = []
        for cv_file in cv_filenames:
            # Check if CV file is in attachments (may be full path or just filename)
            found = False
            for attachment in attachments:
                # Extract filename from attachment (might be full path)
                attachment_filename = attachment.split("/")[-1] if "/" in attachment else attachment

                # Check exact match or contains
                if (
                    cv_file == attachment_filename
                    or cv_file in attachment
                    or attachment.endswith(cv_file)
                ):
                    found = True
                    break
                # Also check if filename matches (case-insensitive)
                if (
                    cv_file.lower() == attachment_filename.lower()
                    or cv_file.lower() in attachment.lower()
                ):
                    found = True
                    break

            if not found:
                missing_cv_files.append(cv_file)

        if missing_cv_files:
            return (
                0.0,
                f"CV files not found in email attachments: {missing_cv_files}. Attachments: {attachments}",
            )

        # ===== CHECK 6: No extra files (non-CV files) are attached =====
        # Check if any recipe files are in attachments
        recipe_filenames = [f["filename"] for f in self.recipe_files_created]

        extra_files = []
        for attachment in attachments:
            # Extract filename from attachment
            attachment_filename = attachment.split("/")[-1] if "/" in attachment else attachment

            # Check if attachment is a recipe file
            for recipe_file in recipe_filenames:
                if (
                    recipe_file == attachment_filename
                    or recipe_file in attachment
                    or attachment.endswith(recipe_file)
                ):
                    extra_files.append(attachment)
                    break

        if extra_files:
            return 0.0, f"Non-CV files incorrectly attached to email: {extra_files}"

        # Also check that we have exactly 3 attachments (all CV files)
        if len(attachments) != 3:
            return (
                0.0,
                f"Expected exactly 3 attachments (3 CV files), found {len(attachments)}: {attachments}",
            )

        # ===== CHECK 6b: Verify all attachments are CV files (not just check against known files) =====
        # Check that all attachments match the *_CV.pdf pattern
        cv_pattern = re.compile(r"^.+_CV\.pdf$", re.IGNORECASE)

        for attachment in attachments:
            attachment_filename = attachment.split("/")[-1] if "/" in attachment else attachment

            # Check if it matches *_CV.pdf pattern
            if not cv_pattern.match(attachment_filename):
                return 0.0, f"Attachment doesn't match *_CV.pdf pattern: {attachment_filename}"

        # ===== CHECK 7: Optional - Verify CV files are indeed within last month =====
        # This is an optional check to ensure date filtering worked correctly
        # We verify that the attached CV files have timestamps within the last month
        #
        download_path = "/sdcard/Download"
        today = datetime.datetime.now()

        for cv_file in self.cv_files_created:
            filename = cv_file["filename"]
            file_path = f"{download_path}/{filename}"

            # Get file modification time
            result = execute_adb(f"shell stat -c %Y {file_path}")

            if result.success:
                try:
                    file_timestamp = int(result.output.strip())
                    days_ago_from_timestamp = (today.timestamp() - file_timestamp) / 86400

                    if days_ago_from_timestamp > 30:
                        logger.warning(
                            f"CV file {filename} has timestamp indicating it's {days_ago_from_timestamp:.1f} days old "
                            f"(expected within 30 days). This may indicate touch -t failed."
                        )
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse timestamp for {filename}")
            else:
                logger.warning(f"Could not get timestamp for {filename}: {result.error}")

        return 1.0, "success"
