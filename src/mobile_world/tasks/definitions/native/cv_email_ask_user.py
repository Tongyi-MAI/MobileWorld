"""CV email task - find recent CV files and send via email."""

import datetime
import os
import random
import re
import tempfile
from typing import Any

from mobile_world.runtime.app_helpers import mail
from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import execute_adb
from mobile_world.tasks.base import BaseTask


def get_device_date(controller: AndroidController) -> datetime.datetime:
    """Get current date from Android device."""
    result = execute_adb("shell date +%Y%m%d")
    if result.success:
        try:
            return datetime.datetime.strptime(result.output.strip(), "%Y%m%d")
        except (ValueError, TypeError):
            pass
    return datetime.datetime.now()


class CVEmailAskUserTask(BaseTask):
    """Find recent CV files and send via email."""

    task_tags = {"agent-user-interaction", "lang-cn"}

    goal = (
        "在Download内找到最近一个月下载的简历文件，把文件发送给我的HR同事，标题为candiaditaes_cv。"
    )

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
    EMAIL_SUBJECT = "candiaditaes_cv"  # Use user's spelling (even if typo)

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
        self.relevant_information = f"My HR colleague's email is {self.EMAIL_ADDRESS}. The email subject is {self.EMAIL_SUBJECT}."

        download_path = "/sdcard/Download"
        today = get_device_date(controller)

        # Clean up any existing *_CV.pdf files
        result = execute_adb(f"shell ls {download_path}/*_CV.pdf")
        if result.success and result.output.strip():
            execute_adb(f"shell rm {download_path}/*_CV.pdf")

        temp_dir = tempfile.mkdtemp()
        failed_files = []

        try:
            # Create 3 CV files (25, 15, 5 days ago)
            for days_ago in [25, 15, 5]:
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

                filepath = os.path.join(temp_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("%PDF-1.4\n")
                    f.write(content)

                remote_path = f"{download_path}/{filename}"
                result = execute_adb(f"push {filepath} {remote_path}")

                if result.success:
                    timestamp_str = date.strftime("%Y%m%d%H%M")
                    execute_adb(f"shell touch -t {timestamp_str} {remote_path}")
                    self.cv_files_created.append({"filename": filename})
                else:
                    failed_files.append(filename)

            # Create 7 recipe files (some within last month, some older)
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

                filepath = os.path.join(temp_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("%PDF-1.4\n")
                    f.write(content)

                remote_path = f"{download_path}/{filename}"
                result = execute_adb(f"push {filepath} {remote_path}")

                if result.success:
                    timestamp_str = date.strftime("%Y%m%d%H%M")
                    execute_adb(f"shell touch -t {timestamp_str} {remote_path}")
                    self.recipe_files_created.append({"filename": filename})
                else:
                    failed_files.append(filename)

        finally:
            for file in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, file))
            os.rmdir(temp_dir)

        if len(failed_files) > 3:
            raise RuntimeError(f"Failed to create {len(failed_files)} files")

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        """Check if the task is successful."""
        self._check_is_initialized()

        sent_email_info = mail.get_sent_email_info()
        if sent_email_info is None:
            return 0.0, "No email sent"

        if sent_email_info.get("to") != self.EMAIL_ADDRESS:
            return 0.0, f"Email sent to wrong address: {sent_email_info.get('to')}"

        if sent_email_info.get("subject", "") != self.EMAIL_SUBJECT:
            return 0.0, f"Email subject is incorrect: '{sent_email_info.get('subject')}'"

        attachments_raw = sent_email_info.get("attachments", [])
        if not attachments_raw:
            return 0.0, "Email has no attachments"

        # Normalize attachments to filenames
        attachments = []
        for att in attachments_raw:
            if isinstance(att, dict):
                att = (
                    att.get("name")
                    or att.get("filename")
                    or att.get("file")
                    or att.get("path")
                    or ""
                )
            if att:
                attachments.append(att)

        if not attachments:
            return 0.0, "Could not parse attachments"

        # Check all CV files are attached
        cv_filenames = {f["filename"] for f in self.cv_files_created}
        attachment_filenames = {att.split("/")[-1].lower() for att in attachments}

        missing = [
            cv
            for cv in cv_filenames
            if cv.lower() not in attachment_filenames
            and not any(cv.lower() in att.lower() for att in attachments)
        ]
        if missing:
            return 0.0, f"CV files not found: {missing}"

        # Check no recipe files and exactly 3 attachments matching CV pattern
        recipe_filenames = {f["filename"] for f in self.recipe_files_created}
        if any(any(recipe in att for recipe in recipe_filenames) for att in attachments):
            return 0.0, "Non-CV files attached"

        if len(attachments) != 3:
            return 0.0, f"Expected 3 attachments, found {len(attachments)}"

        cv_pattern = re.compile(r"^.+_CV\.pdf$", re.IGNORECASE)
        if not all(cv_pattern.match(att.split("/")[-1]) for att in attachments):
            return 0.0, "Not all attachments match *_CV.pdf pattern"

        return 1.0, "success"
