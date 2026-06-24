"""Project paper email task - find project_* PDFs, move to specified folder, and email all files."""

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


class ProjectPaperEmailAskUserTask(BaseTask):
    """Find project_* PDFs, move to specified folder, and email all files."""

    task_tags = {"agent-user-interaction", "lang-cn"}

    goal = "查找手机Documents文件夹内所有project开头的pdf文件，移动到我指定的文件夹下，并把文件夹下的所有文件发送到Catherine，标题为project。"
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

    EMAIL_ADDRESS = "catherine@techshare.com"
    EMAIL_SUBJECT = "project"
    TARGET_STORAGE_FOLDER = "Documents/archive"

    def __init__(self, params: dict[str, Any] = None):
        super().__init__(params)
        self.project_pdf_files = []  # project_* PDF files that should be moved
        self.other_files_created = []  # Other files in folders (should not be moved)
        self.initial_archive_file = None  # Initial file in target storage folder

    def reset_task_state(self) -> None:
        self.project_pdf_files = []
        self.other_files_created = []
        self.initial_archive_file = None

    app_names = {"Files", "Mail"}

    def initialize_task_hook(self, controller: AndroidController) -> None:
        """Create test folders and files."""
        self.relevant_information = f"The email address of Catherine is {self.EMAIL_ADDRESS}. The target saving storage folder is {self.TARGET_STORAGE_FOLDER}."

        # Create 6 random folders
        selected_folders = random.sample(self.FOLDER_NAMES, 6)

        # Select 3 folders that will contain project_* PDF files
        folders_with_project = random.sample(selected_folders, 3)
        folders_without_project = [f for f in selected_folders if f not in folders_with_project]

        logger.info("Creating 6 folders with random files...")
        logger.info(f"Folders with project_* PDFs: {folders_with_project}")
        logger.info(f"Folders without project_* PDFs: {folders_without_project}")

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

                has_project_pdf = folder_name in folders_with_project

                logger.info(f"\nCreating folder: {folder_name}")
                logger.info(f"  Will contain project_* PDF: {has_project_pdf}")
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

                # If this folder should have project_* PDF, create one
                if has_project_pdf:
                    # Random suffix for project_* file
                    suffixes = ["v1", "v2", "final", "draft", "revised", "submitted", "accepted"]
                    suffix = random.choice(suffixes)
                    project_filename = f"project_{suffix}.pdf"

                    title = f"Project Document: {suffix}"
                    content_text = f"""Project Document: {suffix}

This is a project document with suffix: {suffix}

Project Content:
- Section 1: Introduction
- Section 2: Methodology
- Section 3: Results
- Section 4: Discussion
- Section 5: Conclusion

Author: Test Author
Date: 2024-11-07
"""

                    # Create local file with valid PDF structure
                    filepath = os.path.join(temp_dir, project_filename)

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
                        failed_files.append(project_filename)
                        logger.error(f"  Failed to create local PDF file: {filepath}")
                        continue

                    file_size = os.path.getsize(filepath)
                    logger.info(f"  Created local PDF file: {filepath} (size: {file_size} bytes)")

                    # Push to Android using controller to ensure correct device
                    remote_path = f"{folder_path}/{project_filename}"
                    logger.info(
                        f"  Pushing PDF to Android device '{controller.device}': {filepath} -> {remote_path}"
                    )

                    # Use controller.push_file to ensure correct device is used
                    result = controller.push_file(filepath, remote_path)

                    if not result.success:
                        failed_files.append(project_filename)
                        logger.error(f"  Failed to push {project_filename} to {remote_path}")
                        logger.error(f"     Error: {result.error}")
                        continue

                    logger.info("  - Push command succeeded, verifying file on device...")

                    # Wait a moment for file to be written
                    time.sleep(0.5)

                    # Verify file exists on Android device using controller's device
                    verify_cmd = f"adb -s {controller.device} shell test -f {remote_path} && echo EXISTS || echo NOT_EXISTS"
                    verify_result = execute_adb(verify_cmd)

                    if verify_result.success and "EXISTS" in verify_result.output:
                        # Get file size on device
                        size_cmd = f"adb -s {controller.device} shell stat -c %s {remote_path}"
                        size_result = execute_adb(size_cmd)
                        if size_result.success:
                            device_size = size_result.output.strip()
                            logger.info(f"  - PDF file verified on device: {remote_path}")
                            logger.info(
                                f"     Local size: {file_size} bytes, Device size: {device_size} bytes"
                            )
                            if file_size != int(device_size):
                                logger.warning(
                                    f"     -  Size mismatch! Local: {file_size}, Device: {device_size}"
                                )
                        else:
                            logger.info(f"  - PDF file verified on device: {remote_path}")

                        # List files in the directory to confirm
                        list_cmd = f"adb -s {controller.device} shell ls -lh {folder_path}"
                        list_result = execute_adb(list_cmd)
                        if list_result.success:
                            logger.info(f"  Files in {folder_path}:")
                            for line in list_result.output.strip().split("\n"):
                                if project_filename in line:
                                    logger.info(f"    to {line.strip()}")

                        self.project_pdf_files.append(
                            {
                                "filename": project_filename,
                                "original_folder": folder_name,
                                "original_path": remote_path,
                                "expected_path": f"/sdcard/{self.TARGET_STORAGE_FOLDER}/{project_filename}",
                            }
                        )
                        logger.info(
                            f"  - Successfully created and verified project PDF: {project_filename}"
                        )
                    else:
                        failed_files.append(project_filename)
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

            # Create target storage directory and initial file
            archive_path = f"/sdcard/{self.TARGET_STORAGE_FOLDER}"
            execute_adb(f"shell mkdir -p {archive_path}")

            # Create initial *.txt file in target storage folder
            initial_filename = f"archive_{random.randint(1, 1000)}.txt"
            initial_content = f"""Archive Document

This is an initial file in {self.TARGET_STORAGE_FOLDER} directory.

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
            remote_path = f"{archive_path}/{initial_filename}"
            result = execute_adb(f"push {filepath} {remote_path}")

            if result.success:
                self.initial_archive_file = {"filename": initial_filename, "path": remote_path}
                logger.info(
                    f"\nCreated initial file in {self.TARGET_STORAGE_FOLDER}: {initial_filename}"
                )
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

        logger.info(f"\n{'=' * 60}")
        logger.info("Total files created:")
        logger.info(f"  - Project PDF files (to be moved): {len(self.project_pdf_files)}")
        logger.info(f"  - Other files (should not be moved): {len(self.other_files_created)}")
        logger.info(f"  - Initial file in {self.TARGET_STORAGE_FOLDER}: 1")
        logger.info(f"\nProject PDF files to be moved to {self.TARGET_STORAGE_FOLDER}:")
        for project_file in self.project_pdf_files:
            logger.info(f"  to {project_file['original_path']} to {project_file['expected_path']}")
        logger.info(f"\nExpected files in {self.TARGET_STORAGE_FOLDER} after move (4 total):")
        logger.info(f"  - {self.initial_archive_file['filename']} (initial)")
        for project_file in self.project_pdf_files:
            logger.info(f"  - {project_file['filename']} (moved)")
        logger.info(f"{'=' * 60}")

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        """
        Check if the task is successful.

        Validation criteria (all must pass to get score 1.0):
        1. All 3 project_* PDF files are moved to target storage folder
        2. No files that don't match project_* pattern are moved
        3. All 4 files in target storage folder are sent via email
        4. Email is sent to catherine@techshare.com
        5. Email subject is "project"
        """
        self._check_is_initialized()

        archive_path = f"/sdcard/{self.TARGET_STORAGE_FOLDER}"

        # ===== CHECK 1: Verify all project_* PDF files are in target storage folder =====
        result = execute_adb(f"shell ls {archive_path}")
        if not result.success:
            return 0.0, f"Failed to list {self.TARGET_STORAGE_FOLDER} directory: {result.error}"

        files_in_archive = [f.strip() for f in result.output.strip().split("\n") if f.strip()]

        logger.info(f"Files in {self.TARGET_STORAGE_FOLDER}: {files_in_archive}")

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

        # Check that all 3 project_* PDF files are in target storage folder (including auto-renamed versions)
        project_filenames = [f["filename"] for f in self.project_pdf_files]

        missing_project_files = []
        found_project_files = []
        for project_file in project_filenames:
            found = False
            for actual_file in files_in_archive:
                if matches_filename(project_file, actual_file):
                    found_project_files.append(actual_file)
                    found = True
                    break
            if not found:
                missing_project_files.append(project_file)

        if missing_project_files:
            return (
                0.0,
                f"Project PDF files not moved to {self.TARGET_STORAGE_FOLDER}: {missing_project_files}",
            )

        # ===== CHECK 2: Verify no files that don't match project_* pattern are moved =====
        # Check that no other files (non-project_* PDFs) are in target storage folder
        # Expected: 4 files total (3 project_* PDFs + 1 initial txt file)
        # Note: found_project_files contains the actual filenames (may include auto-renamed versions)
        expected_files_set = set(found_project_files + [self.initial_archive_file["filename"]])

        # Also check for expected files using original filenames (in case they weren't auto-renamed)
        for project_file in project_filenames:
            if project_file in files_in_archive:
                expected_files_set.add(project_file)

        extra_files = set(files_in_archive) - expected_files_set
        if extra_files:
            return (
                0.0,
                f"Unexpected files in {self.TARGET_STORAGE_FOLDER} (non-project_* files incorrectly moved?): {extra_files}",
            )

        # Also check that no other project_* files (not from our initialization) are in target storage folder
        project_pattern = re.compile(r"^project_.*\.pdf$", re.IGNORECASE)
        for file in files_in_archive:
            if project_pattern.match(file):
                # Check if this file matches any of our expected project files (including auto-renamed)
                matches_expected = False
                for project_file in project_filenames:
                    if matches_filename(project_file, file):
                        matches_expected = True
                        break
                if not matches_expected:
                    return (
                        0.0,
                        f"Unexpected project_* file in {self.TARGET_STORAGE_FOLDER} (not from initialization): {file}",
                    )

        # ===== CHECK 3: Verify files are no longer in original folders =====
        # Check that project_* PDF files are removed from original folders
        # Note: Files should be MOVED (not copied), so they should not exist in original location
        files_still_in_original = []
        for project_file in self.project_pdf_files:
            original_path = project_file["original_path"]
            original_folder = project_file["original_folder"]
            filename = project_file["filename"]

            # Check if file exists in original location using controller's device
            check_cmd = f"adb -s {controller.device} shell test -f {original_path} && echo EXISTS || echo NOT_EXISTS"
            result = execute_adb(check_cmd)

            logger.info(f"  Checking original location for {filename}: {original_path}")
            output_stripped = result.output.strip() if result.success else result.error
            logger.info(f"    Command result: success={result.success}, output={output_stripped}")

            # Check if output equals "EXISTS" (not just contains it, since "NOT_EXISTS" contains "EXISTS")
            if result.success and output_stripped == "EXISTS":
                # File still exists in original location - this means file was copied, not moved
                files_still_in_original.append(
                    {
                        "filename": filename,
                        "original_path": original_path,
                        "original_folder": original_folder,
                    }
                )
                logger.warning(f"  -  File still exists in original location: {original_path}")

                # Also verify the file exists in target location
                target_path = f"{archive_path}/{filename}"
                target_check_cmd = f"adb -s {controller.device} shell test -f {target_path} && echo EXISTS || echo NOT_EXISTS"
                target_result = execute_adb(target_check_cmd)
                target_output_stripped = (
                    target_result.output.strip() if target_result.success else target_result.error
                )
                if target_result.success and target_output_stripped == "EXISTS":
                    logger.warning("  -  File exists in BOTH locations (copied, not moved):")
                    logger.warning(f"     Original: {original_path}")
                    logger.warning(f"     Target: {target_path}")

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
                "Project files still exist in original locations (files were copied, not moved):\n"
            )
            for file_info in files_still_in_original:
                error_msg += f"  - {file_info['filename']} in {file_info['original_folder']}: {file_info['original_path']}\n"
            error_msg += "\nNote: Task requires MOVING files (not copying). Please delete files from original locations after moving."
            return 0.0, error_msg.strip()

        # ===== CHECK 4: Verify exactly 4 files in target storage folder =====
        if len(files_in_archive) != 4:
            return (
                0.0,
                f"Expected exactly 4 files in {self.TARGET_STORAGE_FOLDER} (3 project_* PDFs + 1 initial txt), found {len(files_in_archive)}: {files_in_archive}",
            )

        # ===== CHECK 5: Email was sent =====
        sent_email_info = mail.get_sent_email_info()

        if sent_email_info is None:
            return 0.0, "No email sent"

        # ===== CHECK 6: Email sent to correct address =====
        if sent_email_info.get("to") != self.EMAIL_ADDRESS:
            return (
                0.0,
                f"Email sent to wrong address: {sent_email_info.get('to')} (expected: {self.EMAIL_ADDRESS})",
            )

        # ===== CHECK 7: Email subject is correct =====
        subject = sent_email_info.get("subject", "")
        if subject != self.EMAIL_SUBJECT:
            return (
                0.0,
                f"Email subject is incorrect: '{subject}' (expected: '{self.EMAIL_SUBJECT}')",
            )

        # ===== CHECK 8: Check attachments =====
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

        logger.info(f"Email attachments: {attachments}")

        # ===== CHECK 9: All 4 files in target storage folder are attached =====
        # Use found_project_files (actual filenames, may include auto-renamed versions) instead of project_filenames
        expected_archive_files = found_project_files + [self.initial_archive_file["filename"]]

        missing_archive_files = []
        for archive_file in expected_archive_files:
            found = False
            for attachment in attachments:
                attachment_filename = attachment.split("/")[-1] if "/" in attachment else attachment

                # Check exact match or if attachment matches the archive file (including auto-renamed versions)
                if (
                    archive_file == attachment_filename
                    or archive_file in attachment
                    or attachment.endswith(archive_file)
                ):
                    found = True
                    break
                if (
                    archive_file.lower() == attachment_filename.lower()
                    or archive_file.lower() in attachment.lower()
                ):
                    found = True
                    break
                # Also check if attachment matches any of the original project filenames (for auto-renamed files)
                for project_file in project_filenames:
                    if matches_filename(project_file, attachment_filename):
                        found = True
                        break
                if found:
                    break

            if not found:
                missing_archive_files.append(archive_file)

        if missing_archive_files:
            return (
                0.0,
                f"Files from {self.TARGET_STORAGE_FOLDER} not found in email attachments: {missing_archive_files}. Attachments: {attachments}",
            )

        # ===== CHECK 10: Exactly 4 attachments (all files from target storage folder) =====
        if len(attachments) != 4:
            return (
                0.0,
                f"Expected exactly 4 attachments (all files from {self.TARGET_STORAGE_FOLDER}), found {len(attachments)}: {attachments}",
            )

        # ===== CHECK 11: No extra files attached =====
        # Verify all attachments are from target storage folder (including auto-renamed versions)
        expected_files_for_attachment_check = set(
            found_project_files + [self.initial_archive_file["filename"]]
        )
        # Also add original filenames in case they weren't auto-renamed
        for project_file in project_filenames:
            expected_files_for_attachment_check.add(project_file)

        for attachment in attachments:
            attachment_filename = attachment.split("/")[-1] if "/" in attachment else attachment

            # Check if attachment matches any expected file (including auto-renamed versions)
            matches_expected = False
            if attachment_filename in expected_files_for_attachment_check:
                matches_expected = True
            else:
                # Check if it's an auto-renamed version of an expected file
                for expected_file in expected_files_for_attachment_check:
                    if matches_filename(expected_file, attachment_filename):
                        matches_expected = True
                        break

            if not matches_expected:
                return (
                    0.0,
                    f"Unexpected file in email attachments (not from {self.TARGET_STORAGE_FOLDER}): {attachment_filename}",
                )

        return 1.0, "success"
