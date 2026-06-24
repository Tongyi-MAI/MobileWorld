"""Review paper email task - find review_* PDFs, move to Document/paper, and email all files."""

import os
import random
import re
import tempfile
import time
from typing import Any

from loguru import logger

from mobile_world.runtime.app_helpers import mail
from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import execute_adb
from mobile_world.tasks.base import BaseTask


class ReviewPaperEmailTask(BaseTask):
    """Find review_* PDFs, move to Document/paper, and email all files."""

    goal = "查找手机Documents文件夹内所有review开头的pdf文件，移动在Document/paper下，并将paper目录下的所有文件，发送到chen@gmail.com，标题为paper。"
    snapshot_tag = "init_state"

    # Random folder names
    FOLDER_NAMES = [
        "Project_A",
        "Project_B",
        "Project_C",
        "Project_D",
        "Project_E",
        "Project_F",
        "Research_1",
        "Research_2",
        "Research_3",
        "Research_4",
        "Research_5",
        "Research_6",
        "Study_Alpha",
        "Study_Beta",
        "Study_Gamma",
        "Study_Delta",
        "Study_Epsilon",
        "Study_Zeta",
        "Analysis_X",
        "Analysis_Y",
        "Analysis_Z",
        "Data_Set_1",
        "Data_Set_2",
        "Data_Set_3",
    ]

    # Random file names (without extension)
    FILE_NAME_BASES = [
        "report",
        "data",
        "analysis",
        "summary",
        "notes",
        "findings",
        "results",
        "conclusion",
        "methodology",
        "discussion",
        "abstract",
        "introduction",
        "background",
        "literature",
        "experiment",
        "observation",
    ]

    EMAIL_ADDRESS = "chen@gmail.com"
    EMAIL_SUBJECT = "paper"

    task_tags = {"lang-cn"}

    def __init__(self, params: dict[str, Any] = None):
        super().__init__(params)
        self.review_pdf_files = []  # review_* PDF files that should be moved
        self.other_files_created = []  # Other files in folders (should not be moved)
        self.initial_paper_file = None  # Initial file in Document/paper

    def reset_task_state(self) -> None:
        self.review_pdf_files = []
        self.other_files_created = []
        self.initial_paper_file = None

    app_names = {"Files", "Mail"}

    def initialize_task_hook(self, controller: AndroidController) -> None:
        """Create test folders and files."""

        # Create 6 random folders
        selected_folders = random.sample(self.FOLDER_NAMES, 6)

        # Select 3 folders that will contain review_* PDF files
        folders_with_review = random.sample(selected_folders, 3)
        folders_without_review = [f for f in selected_folders if f not in folders_with_review]

        logger.info("Creating 6 folders with random files...")
        logger.info(f"Folders with review_* PDFs: {folders_with_review}")
        logger.info(f"Folders without review_* PDFs: {folders_without_review}")

        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        failed_files = []

        try:
            # Create files in each folder
            for folder_name in selected_folders:
                folder_path = f"/sdcard/Documents/{folder_name}"

                # Create folder
                execute_adb(f"shell mkdir -p {folder_path}")

                # Determine how many files to create in this folder (random: 1-4 files)
                num_files = random.randint(1, 4)

                # Determine file types (csv, doc, txt)
                file_types = random.sample(["csv", "doc", "txt"], random.randint(1, 3))

                has_review_pdf = folder_name in folders_with_review

                logger.info(f"\nCreating folder: {folder_name}")
                logger.info(f"  Will contain review_* PDF: {has_review_pdf}")
                logger.info(f"  Number of files: {num_files}")
                logger.info(f"  File types: {file_types}")

                # Create regular files (csv, doc, txt)
                for i in range(num_files):
                    base_name = random.choice(self.FILE_NAME_BASES)
                    file_type = random.choice(file_types)
                    filename = f"{base_name}_{random.randint(1, 1000)}.{file_type}"

                    content = f"""File: {filename}
Folder: {folder_name}
Type: {file_type}

Content:
This is a {file_type} file in folder {folder_name}.
Generated for testing purposes.

Data:
- Item 1
- Item 2
- Item 3
"""

                    # Create local file
                    filepath = os.path.join(temp_dir, filename)
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(content)

                    # Push to Android
                    remote_path = f"{folder_path}/{filename}"
                    result = execute_adb(f"push {filepath} {remote_path}")

                    if result.success:
                        self.other_files_created.append(
                            {"filename": filename, "folder": folder_name, "path": remote_path}
                        )
                        logger.info(f"  Created: {filename}")
                    else:
                        failed_files.append(filename)
                        logger.error(f"  Failed to create {filename}: {result.error}")

                # If this folder should have review_* PDF, create one
                if has_review_pdf:
                    # Random suffix for review_* file
                    suffixes = ["v1", "v2", "final", "draft", "revised", "submitted", "accepted"]
                    suffix = random.choice(suffixes)
                    review_filename = f"review_{suffix}.pdf"

                    title = f"Review Document: {suffix}"
                    content_text = f"""Review Document: {suffix}

This is a review document with suffix: {suffix}

Review Content:
- Section 1: Introduction
- Section 2: Methodology
- Section 3: Results
- Section 4: Discussion
- Section 5: Conclusion

Reviewer: Test Reviewer
Date: 2024-11-07
"""

                    # Create local file with valid PDF structure
                    filepath = os.path.join(temp_dir, review_filename)

                    # Escape text for PDF content stream (escape parentheses and backslashes)
                    def escape_pdf_text(text):
                        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

                    escaped_title = escape_pdf_text(title)
                    escaped_content = escape_pdf_text(content_text[:300])

                    # Calculate stream length
                    stream_content = f"""BT
/F1 14 Tf
50 750 Td
({escaped_title}) Tj
0 -30 Td
/F1 10 Tf
({escaped_content}) Tj
ET
"""
                    stream_length = len(stream_content)

                    # Build PDF content
                    pdf_parts = [
                        "%PDF-1.4",
                        "1 0 obj",
                        "<<",
                        "/Type /Catalog",
                        "/Pages 2 0 R",
                        ">>",
                        "endobj",
                        "2 0 obj",
                        "<<",
                        "/Type /Pages",
                        "/Kids [3 0 R]",
                        "/Count 1",
                        ">>",
                        "endobj",
                        "3 0 obj",
                        "<<",
                        "/Type /Page",
                        "/Parent 2 0 R",
                        "/MediaBox [0 0 612 792]",
                        "/Contents 4 0 R",
                        "/Resources <<",
                        "/Font <<",
                        "/F1 <<",
                        "/Type /Font",
                        "/Subtype /Type1",
                        "/BaseFont /Helvetica",
                        ">>",
                        ">>",
                        ">>",
                        ">>",
                        "endobj",
                        "4 0 obj",
                        f"<<\n/Length {stream_length}\n>>",
                        "stream",
                        stream_content,
                        "endstream",
                        "endobj",
                    ]

                    pdf_body = "\n".join(pdf_parts)
                    xref_offset = len(pdf_body.encode("utf-8"))

                    pdf_content = f"""{pdf_body}
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000317 00000 n
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
{xref_offset}
%%EOF
"""

                    with open(filepath, "wb") as f:
                        f.write(pdf_content.encode("utf-8"))

                    # Verify local file was created
                    if not os.path.exists(filepath):
                        failed_files.append(review_filename)
                        logger.error(f"  Failed to create local PDF file: {filepath}")
                        continue

                    file_size = os.path.getsize(filepath)
                    logger.info(f"  Created local PDF file: {filepath} (size: {file_size} bytes)")

                    # Push to Android using controller to ensure correct device
                    remote_path = f"{folder_path}/{review_filename}"
                    logger.info(
                        f"  Pushing PDF to Android device '{controller.device}': {filepath} -> {remote_path}"
                    )

                    # Use controller.push_file to ensure correct device is used
                    result = controller.push_file(filepath, remote_path)

                    if not result.success:
                        failed_files.append(review_filename)
                        logger.error(f"  Failed to push {review_filename} to {remote_path}")
                        logger.error(f"     Error: {result.error}")
                        continue

                    # Wait a moment for file to be written
                    time.sleep(0.5)

                    # Verify file exists on Android device using controller's device
                    verify_cmd = f"adb -s {controller.device} shell test -f {remote_path} && echo EXISTS || echo NOT_EXISTS"
                    verify_result = execute_adb(verify_cmd)

                    if verify_result.success and "EXISTS" in verify_result.output:
                        size_cmd = f"adb -s {controller.device} shell stat -c %s {remote_path}"
                        size_result = execute_adb(size_cmd)
                        if size_result.success:
                            device_size = size_result.output.strip()
                            if file_size != int(device_size):
                                logger.warning(
                                    f"Size mismatch! Local: {file_size}, Device: {device_size}"
                                )

                        # List files in the directory to confirm
                        list_cmd = f"adb -s {controller.device} shell ls -lh {folder_path}"
                        list_result = execute_adb(list_cmd)
                        if list_result.success:
                            logger.info(f"  Files in {folder_path}:")
                            for line in list_result.output.strip().split("\n"):
                                if review_filename in line:
                                    logger.info(f"    to {line.strip()}")

                        self.review_pdf_files.append(
                            {
                                "filename": review_filename,
                                "original_folder": folder_name,
                                "original_path": remote_path,
                                "expected_path": f"/sdcard/Documents/paper/{review_filename}",
                            }
                        )
                    else:
                        failed_files.append(review_filename)
                        logger.error(f"  PDF file not found on device after push: {remote_path}")
                        logger.error(
                            f"     Verification command output: {verify_result.output if verify_result.success else verify_result.error}"
                        )

                        # Try to list directory contents to debug
                        list_cmd = f"adb -s {controller.device} shell ls -la {folder_path}"
                        list_result = execute_adb(list_cmd)
                        if list_result.success:
                            logger.error("     Directory contents:")
                            for line in list_result.output.strip().split("\n"):
                                logger.error(f"       {line}")
                        else:
                            logger.error(f"     Failed to list directory: {list_result.error}")

            # Create Document/paper directory and initial file
            paper_path = "/sdcard/Documents/paper"
            execute_adb(f"shell mkdir -p {paper_path}")

            # Create initial *.txt file in Document/paper
            initial_filename = f"paper_{random.randint(1, 1000)}.txt"
            initial_content = """Paper Document

This is an initial file in Document/paper directory.

Content:
- Initial notes
- References
- Bibliography

Created: 2024-11-07
"""

            # Create local file
            filepath = os.path.join(temp_dir, initial_filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(initial_content)

            # Push to Android
            remote_path = f"{paper_path}/{initial_filename}"
            result = execute_adb(f"push {filepath} {remote_path}")

            if result.success:
                self.initial_paper_file = {"filename": initial_filename, "path": remote_path}
                logger.info(f"\nCreated initial file in Document/paper: {initial_filename}")
            else:
                failed_files.append(initial_filename)
                logger.error(f"Failed to create initial file: {result.error}")

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

        logger.info(
            f"Total files created: Review PDFs: {len(self.review_pdf_files)}, Other: {len(self.other_files_created)}"
        )

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        """
        Check if the task is successful.

        Validation criteria (all must pass to get score 1.0):
        1. All 3 review_* PDF files are moved to Document/paper
        2. No files that don't match review_* pattern are moved
        3. All 4 files in Document/paper are sent via email
        4. Email is sent to chen@gmail.com
        5. Email subject is "paper"
        """
        self._check_is_initialized()

        paper_path = "/sdcard/Documents/paper"

        # ===== CHECK 1: Verify all review_* PDF files are in Document/paper =====
        result = execute_adb(f"shell ls {paper_path}")
        if not result.success:
            return 0.0, f"Failed to list Document/paper directory: {result.error}"

        files_in_paper = [f.strip() for f in result.output.strip().split("\n") if f.strip()]

        logger.info(f"Files in Document/paper: {files_in_paper}")

        # Helper function to match filenames including auto-renamed versions
        # Android automatically renames duplicate files as "filename (1).ext", "filename (2).ext", etc.
        def matches_filename(expected_filename: str, actual_filename: str) -> bool:
            """Check if actual_filename matches expected_filename or its auto-renamed version."""
            if actual_filename == expected_filename:
                return True
            # Check for auto-renamed versions: "filename (1).ext", "filename (2).ext", etc.
            base_name, ext = os.path.splitext(expected_filename)
            auto_rename_pattern = re.compile(
                rf"^{re.escape(base_name)}\s*\(\d+\){re.escape(ext)}$", re.IGNORECASE
            )
            return bool(auto_rename_pattern.match(actual_filename))

        # Check that all 3 review_* PDF files are in Document/paper (including auto-renamed versions)
        review_filenames = [f["filename"] for f in self.review_pdf_files]

        missing_review_files = []
        found_review_files = []
        for review_file in review_filenames:
            found = False
            for actual_file in files_in_paper:
                if matches_filename(review_file, actual_file):
                    found_review_files.append(actual_file)
                    found = True
                    break
            if not found:
                missing_review_files.append(review_file)

        if missing_review_files:
            return 0.0, f"Review PDF files not moved to Document/paper: {missing_review_files}"

        # ===== CHECK 2: Verify no files that don't match review_* pattern are moved =====
        # Check that no other files (non-review_* PDFs) are in Document/paper
        # Expected: 4 files total (3 review_* PDFs + 1 initial txt file)
        # Note: found_review_files contains the actual filenames (may include auto-renamed versions)
        expected_files_set = set(found_review_files + [self.initial_paper_file["filename"]])

        # Also check for expected files using original filenames (in case they weren't auto-renamed)
        for review_file in review_filenames:
            if review_file in files_in_paper:
                expected_files_set.add(review_file)

        extra_files = set(files_in_paper) - expected_files_set
        if extra_files:
            return (
                0.0,
                f"Unexpected files in Document/paper (non-review_* files incorrectly moved?): {extra_files}",
            )

        # Also check that no other review_* files (not from our initialization) are in Document/paper
        review_pattern = re.compile(r"^review_.*\.pdf$", re.IGNORECASE)
        for file in files_in_paper:
            if review_pattern.match(file):
                # Check if this file matches any of our expected review files (including auto-renamed)
                matches_expected = False
                for review_file in review_filenames:
                    if matches_filename(review_file, file):
                        matches_expected = True
                        break
                if not matches_expected:
                    return (
                        0.0,
                        f"Unexpected review_* file in Document/paper (not from initialization): {file}",
                    )

        # ===== CHECK 3: Verify files are no longer in original folders =====
        # Check that review_* PDF files are removed from original folders
        # Note: Files should be MOVED (not copied), so they should not exist in original location
        files_still_in_original = []
        for review_file in self.review_pdf_files:
            original_path = review_file["original_path"]
            original_folder = review_file["original_folder"]
            filename = review_file["filename"]

            # Check if file exists in original location using controller's device
            check_cmd = f"adb -s {controller.device} shell test -f {original_path} && echo EXISTS || echo NOT_EXISTS"
            result = execute_adb(check_cmd)

            logger.info(f"  Checking original location for {filename}: {original_path}")
            output_stripped = result.output.strip() if result.success else result.error
            logger.info(f"    Command result: success={result.success}, output={output_stripped}")

            # Check if output equals "EXISTS" (not just contains it, since "NOT_EXISTS" contains "EXISTS")
            if result.success and output_stripped == "EXISTS":
                files_still_in_original.append(
                    {
                        "filename": filename,
                        "original_path": original_path,
                        "original_folder": original_folder,
                    }
                )
                logger.warning(f"  ⚠️  File still exists in original location: {original_path}")

                # Also verify the file exists in target location
                target_path = f"{paper_path}/{filename}"
                target_check_cmd = f"adb -s {controller.device} shell test -f {target_path} && echo EXISTS || echo NOT_EXISTS"
                target_result = execute_adb(target_check_cmd)
                target_output_stripped = (
                    target_result.output.strip() if target_result.success else target_result.error
                )

            else:
                logger.info(f"  ✓ File removed from original location: {original_path}")

        if files_still_in_original:
            # List all files in the original folders to help debug
            for file_info in files_still_in_original:
                folder_path = f"/sdcard/Documents/{file_info['original_folder']}"
                list_cmd = f"adb -s {controller.device} shell ls -lh {folder_path}"
                list_result = execute_adb(list_cmd)
                if list_result.success:
                    logger.error(f"  Files still in {folder_path}:")
                    for line in list_result.output.strip().split("\n"):
                        if file_info["filename"] in line:
                            logger.error(f"    to {line.strip()}")

            error_msg = (
                "Review files still exist in original locations (files were copied, not moved):\n"
            )
            for file_info in files_still_in_original:
                error_msg += f"  - {file_info['filename']} in {file_info['original_folder']}: {file_info['original_path']}\n"
            error_msg += "\nNote: Task requires MOVING files (not copying). Please delete files from original locations after moving."
            return 0.0, error_msg.strip()

        if len(files_in_paper) != 4:
            return (
                0.0,
                f"Expected exactly 4 files in Document/paper (3 review_* PDFs + 1 initial txt), found {len(files_in_paper)}: {files_in_paper}",
            )

        sent_email_info = mail.get_sent_email_info()

        if sent_email_info is None:
            return 0.0, "No email sent"

        if sent_email_info.get("to") != self.EMAIL_ADDRESS:
            return (
                0.0,
                f"Email sent to wrong address: {sent_email_info.get('to')} (expected: {self.EMAIL_ADDRESS})",
            )

        subject = sent_email_info.get("subject", "")
        if subject != self.EMAIL_SUBJECT:
            return (
                0.0,
                f"Email subject is incorrect: '{subject}' (expected: '{self.EMAIL_SUBJECT}')",
            )

        attachments_raw = sent_email_info.get("attachments", [])

        if not attachments_raw:
            return 0.0, "Email has no attachments"

        # Normalize attachments to list of filenames
        attachments = []
        for att in attachments_raw:
            if isinstance(att, dict):
                if "name" in att:
                    attachments.append(att["name"])
                else:
                    for key in ["filename", "file", "path"]:
                        if key in att:
                            attachments.append(att[key])
                            break
            elif isinstance(att, str):
                attachments.append(att)

        if not attachments:
            return 0.0, f"Could not parse attachments from email info: {attachments_raw}"

        expected_paper_files = found_review_files + [self.initial_paper_file["filename"]]

        missing_paper_files = []
        for paper_file in expected_paper_files:
            found = False
            for attachment in attachments:
                attachment_filename = attachment.split("/")[-1] if "/" in attachment else attachment

                # Check exact match or if attachment matches the paper file (including auto-renamed versions)
                if (
                    paper_file == attachment_filename
                    or paper_file in attachment
                    or attachment.endswith(paper_file)
                ):
                    found = True
                    break
                if (
                    paper_file.lower() == attachment_filename.lower()
                    or paper_file.lower() in attachment.lower()
                ):
                    found = True
                    break
                # Also check if attachment matches any of the original review filenames (for auto-renamed files)
                for review_file in review_filenames:
                    if matches_filename(review_file, attachment_filename):
                        found = True
                        break
                if found:
                    break

            if not found:
                missing_paper_files.append(paper_file)

        if missing_paper_files:
            return (
                0.0,
                f"Files from Document/paper not found in email attachments: {missing_paper_files}. Attachments: {attachments}",
            )

        if len(attachments) != 4:
            return (
                0.0,
                f"Expected exactly 4 attachments (all files from Document/paper), found {len(attachments)}: {attachments}",
            )

        expected_files_for_attachment_check = set(
            found_review_files + [self.initial_paper_file["filename"]]
        )
        for review_file in review_filenames:
            expected_files_for_attachment_check.add(review_file)

        for attachment in attachments:
            attachment_filename = attachment.split("/")[-1] if "/" in attachment else attachment

            matches_expected = False
            if attachment_filename in expected_files_for_attachment_check:
                matches_expected = True
            else:
                for expected_file in expected_files_for_attachment_check:
                    if matches_filename(expected_file, attachment_filename):
                        matches_expected = True
                        break

            if not matches_expected:
                return (
                    0.0,
                    f"Unexpected file in email attachments (not from Document/paper): {attachment_filename}",
                )

        return 1.0, "success"
