"""Bid file renaming task - rename bid_ prefixed files by creation date."""

import datetime
import os
import tempfile
from typing import Any

from loguru import logger

from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import execute_adb
from mobile_world.tasks.base import BaseTask


class BidFileRenameTask(BaseTask):
    """Rename bid_ prefixed files by creation date."""

    goal = "将Download中前缀为bid_的文件, 按创建日期由早到晚，统一按照'bid_{序号}.{原扩展名}'进行重命名。"

    # 4 bid files with menu-related content
    BID_FILES = [
        {
            "original_name": "bid_restaurant_proposal.txt",
            "extension": "txt",
            "content": """Restaurant Menu Bid Proposal

Proposal ID: BID-2024-001
Date: November 1, 2024

Dear Client,

We are pleased to submit our bid for your restaurant menu printing services.

MENU ITEMS INCLUDED:
- Appetizers Section (10 items)
- Main Course Section (25 items)
- Desserts Section (12 items)
- Beverages Section (15 items)

PRINTING SPECIFICATIONS:
- Full color printing on premium paper
- Laminated finish for durability
- Custom layout and design
- 100 copies per order

PRICING:
Total Bid Amount: $2,500
Delivery: 2 weeks

Thank you for considering our proposal.

Best regards,
Menu Printing Services""",
        },
        {
            "original_name": "bid_catering_menu_2024.doc",
            "extension": "doc",
            "content": """Catering Menu Bid

Bid Reference: BID-CAT-2024
Submitted: October 28, 2024

CATERING MENU PACKAGE

BREAKFAST MENU:
- Continental breakfast buffet
- Fresh fruit platter
- Pastries and croissants
- Coffee and tea service

LUNCH MENU:
- Choice of 3 entrees
- Salad bar
- Soup of the day
- Dessert selection

DINNER MENU:
- Appetizer course
- Main course (beef, chicken, or vegetarian)
- Side dishes
- Dessert and coffee

SERVICE DETAILS:
- Full service staff included
- Table setup and cleanup
- Serving utensils and chafing dishes

BID AMOUNT: $45 per person
Minimum order: 50 guests

Valid for 30 days from submission.""",
        },
        {
            "original_name": "bid_menu_design_contract.pdf",
            "extension": "pdf",
            "content": """BID FOR MENU DESIGN SERVICES

Bid Number: MD-2024-055
Date: October 15, 2024

PROJECT SCOPE:
Design and development of restaurant menu

DELIVERABLES:
1. Menu concept and theme design
2. Food photography styling
3. Layout and typography
4. Digital and print-ready formats

MENU SECTIONS TO DESIGN:
- Appetizers and Starters
- Soups and Salads
- Main Dishes
- Chef's Specials
- Desserts
- Wine and Cocktail List

TIMELINE:
- Initial concepts: 1 week
- Revisions: 2 weeks
- Final delivery: 3 weeks total

PRICING BREAKDOWN:
Design fees: $3,000
Photography: $1,500
Revisions (up to 3): Included
Total Bid: $4,500

Terms: 50% deposit, 50% on completion""",
        },
        {
            "original_name": "bid_food_supplier_quote.txt",
            "extension": "txt",
            "content": """Food Supplier Bid Quotation

Bid ID: FS-2024-Q3-089
Quotation Date: September 30, 2024

MENU INGREDIENTS SUPPLY BID

Fresh Produce:
- Seasonal vegetables (daily delivery)
- Fresh fruits
- Herbs and greens

Proteins:
- Premium beef cuts
- Free-range chicken
- Fresh seafood
- Plant-based alternatives

Dairy Products:
- Artisan cheeses
- Fresh cream and butter
- Specialty yogurts

Dry Goods:
- Pasta varieties
- Rice and grains
- Specialty flours
- Spices and seasonings

DELIVERY SCHEDULE:
- Monday, Wednesday, Friday
- Emergency orders available
- Temperature-controlled transport

MONTHLY BID TOTAL: $15,000
(Based on estimated menu requirements)

Payment Terms: Net 30 days
Contract Period: 12 months""",
        },
    ]

    # 11 other files with AI-related content
    OTHER_FILES = [
        {
            "name": "ai_research_paper.pdf",
            "extension": "pdf",
            "content": """AI Research: Neural Network Optimization

Abstract: This paper explores novel approaches to optimizing
deep neural networks for improved performance and efficiency.

Keywords: artificial intelligence, machine learning, optimization""",
        },
        {
            "name": "machine_learning_notes.txt",
            "extension": "txt",
            "content": """Machine Learning Study Notes

Chapter 1: Introduction to AI
- Definition of artificial intelligence
- History and evolution
- Current applications

Chapter 2: Neural Networks
- Perceptrons
- Backpropagation
- Deep learning architectures""",
        },
        {
            "name": "data_analysis_report.doc",
            "extension": "doc",
            "content": """AI-Powered Data Analysis Report

Executive Summary:
Our AI system analyzed 1 million data points to identify
patterns and trends in customer behavior.

Key Findings:
- Machine learning accuracy: 94%
- Processing time reduced by 60%
- Actionable insights generated""",
        },
        {
            "name": "chatbot_training_data.txt",
            "extension": "txt",
            "content": """Chatbot AI Training Dataset

Sample conversations for training conversational AI:
- Customer service queries
- Technical support dialogues
- General information requests

Training examples: 50,000 conversations
Language models: GPT-based architecture""",
        },
        {
            "name": "computer_vision_project.pdf",
            "extension": "pdf",
            "content": """Computer Vision AI Project

Project Title: Image Recognition System

Technology Stack:
- Convolutional Neural Networks (CNN)
- TensorFlow and PyTorch
- OpenCV for preprocessing

Applications:
- Object detection
- Face recognition
- Scene understanding""",
        },
        {
            "name": "nlp_processing_guide.doc",
            "extension": "doc",
            "content": """Natural Language Processing Guide

AI-based text analysis and understanding:

1. Tokenization and preprocessing
2. Named Entity Recognition (NER)
3. Sentiment analysis
4. Text classification
5. Language generation

Tools: spaCy, NLTK, Transformers""",
        },
        {
            "name": "ai_ethics_discussion.txt",
            "extension": "txt",
            "content": """AI Ethics and Responsible AI

Discussion Topics:
- Bias in machine learning models
- Privacy concerns in AI systems
- Transparency and explainability
- AI safety and alignment
- Societal impact of automation""",
        },
        {
            "name": "deep_learning_tutorial.pdf",
            "extension": "pdf",
            "content": """Deep Learning Tutorial

Introduction to Deep Neural Networks

Topics Covered:
- Architecture design
- Activation functions
- Optimization algorithms
- Regularization techniques
- Transfer learning

Frameworks: TensorFlow, Keras, PyTorch""",
        },
        {
            "name": "ai_deployment_strategy.doc",
            "extension": "doc",
            "content": """AI Model Deployment Strategy

Production Deployment Plan:

1. Model Training and Validation
2. API Development
3. Containerization (Docker)
4. Cloud Infrastructure Setup
5. Monitoring and Maintenance

Technologies: Kubernetes, MLOps, CI/CD""",
        },
        {
            "name": "recommendation_system.txt",
            "extension": "txt",
            "content": """AI Recommendation System

Collaborative Filtering Algorithm

Features:
- User-based recommendations
- Item-based filtering
- Matrix factorization
- Neural collaborative filtering

Use cases: e-commerce, streaming, content""",
        },
        {
            "name": "ai_performance_metrics.pdf",
            "extension": "pdf",
            "content": """AI Model Performance Metrics

Evaluation Metrics:
- Accuracy, Precision, Recall
- F1 Score
- ROC-AUC
- Mean Squared Error (MSE)
- Confusion Matrix Analysis

Benchmarking results and comparisons.""",
        },
    ]

    task_tags = {"lang-cn"}

    def __init__(self, params: dict[str, Any] = None):
        super().__init__(params)
        self.bid_files_created = []  # Store info about bid files (name, date, extension)
        self.other_files_created = []  # Store info about non-bid files

    def reset_task_state(self) -> None:
        self.bid_files_created = []
        self.other_files_created = []

    app_names = {
        "Files",
    }

    def initialize_task_hook(self, controller: AndroidController) -> None:
        """Create test files in Download directory."""

        download_path = "/sdcard/Download"
        today = datetime.datetime.now()

        logger.info("Creating bid files and other files in Download directory...")

        # Clean up any existing bid_ files to avoid interference
        result = execute_adb(f"shell ls {download_path}/bid_*")
        if result.success and result.output.strip():
            logger.info("Cleaning up existing bid_* files...")
            execute_adb(f"shell rm {download_path}/bid_*")

        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        failed_files = []

        try:
            # Create 4 bid files with different creation dates
            # Dates: 25, 18, 10, 3 days ago (from old to new)
            bid_days_ago = [25, 18, 10, 3]

            for i, (days_ago, bid_file) in enumerate(zip(bid_days_ago, self.BID_FILES)):
                date = today - datetime.timedelta(days=days_ago)

                original_name = bid_file["original_name"]
                extension = bid_file["extension"]
                content = bid_file["content"]

                # Create local file
                filepath = os.path.join(temp_dir, original_name)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)

                # Push to Android
                remote_path = f"{download_path}/{original_name}"
                result = execute_adb(f"push {filepath} {remote_path}")

                if result.success:
                    # Set file creation/modification time
                    timestamp_str = date.strftime("%Y%m%d%H%M")
                    execute_adb(f"shell touch -t {timestamp_str} {remote_path}")

                    self.bid_files_created.append(
                        {
                            "original_name": original_name,
                            "extension": extension,
                            "days_ago": days_ago,
                            "date": date,
                            "expected_new_name": f"bid_{i + 1}.{extension}",  # Expected name after rename
                        }
                    )

                    logger.info(
                        f"Created bid file: {original_name} ({days_ago} days ago) - Menu content"
                    )
                else:
                    failed_files.append(original_name)
                    logger.error(f"Failed to create {original_name}: {result.error}")

            # Sort bid files by date (earliest first) for expected order
            self.bid_files_created.sort(key=lambda x: x["days_ago"], reverse=True)

            # Update expected new names based on sorted order
            for i, bid_file in enumerate(self.bid_files_created):
                bid_file["expected_new_name"] = f"bid_{i + 1}.{bid_file['extension']}"

            # Create 11 other files (non-bid) with various dates
            other_days_ago = [30, 22, 15, 12, 8, 6, 4, 2, 1, 20, 14]

            for days_ago, other_file in zip(other_days_ago, self.OTHER_FILES):
                date = today - datetime.timedelta(days=days_ago)

                filename = other_file["name"]
                content = other_file["content"]

                # Create local file
                filepath = os.path.join(temp_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)

                # Push to Android
                remote_path = f"{download_path}/{filename}"
                result = execute_adb(f"push {filepath} {remote_path}")

                if result.success:
                    # Set file creation/modification time
                    timestamp_str = date.strftime("%Y%m%d%H%M")
                    execute_adb(f"shell touch -t {timestamp_str} {remote_path}")

                    self.other_files_created.append(
                        {"name": filename, "days_ago": days_ago, "should_not_change": True}
                    )

                    logger.info(
                        f"Created other file: {filename} ({days_ago} days ago) - AI content"
                    )
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
            if len(failed_files) > 5:
                raise RuntimeError(
                    f"Failed to create {len(failed_files)} files. Task initialization failed."
                )

        logger.info(f"\n{'=' * 60}")
        logger.info(
            f"Total files created: {len(self.bid_files_created) + len(self.other_files_created)}"
        )
        logger.info(f"  - Bid files (to be renamed): {len(self.bid_files_created)}")
        logger.info(f"  - Other files (should not change): {len(self.other_files_created)}")
        logger.info("\nExpected renaming order (by creation date, earliest to latest):")
        for i, bid_file in enumerate(self.bid_files_created, 1):
            logger.info(
                f"  {i}. {bid_file['original_name']} to {bid_file['expected_new_name']} ({bid_file['days_ago']} days ago)"
            )
        logger.info(f"{'=' * 60}")

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        """
        Check if the task is successful.

        Validation criteria (all must pass to get score 1.0):
        1. Bid files are renamed correctly to bid_{序号}.{原扩展名}
        2. Sequence numbers match creation date order (earliest = 1)
        3. No non-bid files were incorrectly renamed
        4. No bid files were missed (all renamed)
        """
        self._check_is_initialized()

        download_path = "/sdcard/Download"

        result = execute_adb(f"shell ls -l {download_path}")
        if not result.success:
            return 0.0, f"Failed to list Download directory: {result.error}"

        lines = result.output.strip().split("\n")

        current_files = []
        for line in lines:
            if not line.strip() or line.startswith("total") or line.startswith("d"):
                continue

            parts = line.split()
            if len(parts) >= 8:
                filename = " ".join(parts[7:])
                current_files.append(filename)

        logger.info(f"Files in Download: {current_files}")

        # ===== CHECK 1: All bid files should be renamed =====
        original_bid_names = [f["original_name"] for f in self.bid_files_created]

        missed_files = [name for name in original_bid_names if name in current_files]
        if missed_files:
            return 0.0, f"Bid files not renamed (missed): {missed_files}"

        # ===== CHECK 2: New bid files exist with correct naming format =====
        expected_new_names = [f["expected_new_name"] for f in self.bid_files_created]

        found_bid_files = [f for f in current_files if f.startswith("bid_")]

        # Check if we have exactly 4 bid_ files
        if len(found_bid_files) != 4:
            return (
                0.0,
                f"Expected 4 renamed bid files, found {len(found_bid_files)}: {found_bid_files}",
            )

        # ===== CHECK 3: Verify each renamed file matches expected name and extension =====
        for expected_file in expected_new_names:
            if expected_file not in found_bid_files:
                return (
                    0.0,
                    f"Expected renamed file not found: {expected_file}. Found: {found_bid_files}",
                )

        # ===== CHECK 4: Verify sequence numbers match creation date order =====
        # Get creation times of renamed files to verify order
        bid_file_times = {}

        for i, expected_bid in enumerate(self.bid_files_created, 1):
            expected_name = expected_bid["expected_new_name"]

            if expected_name not in found_bid_files:
                return 0.0, f"Expected file {expected_name} not found in renamed files"

            expected_ext = expected_bid["extension"]
            if not expected_name.endswith(f".{expected_ext}"):
                return (
                    0.0,
                    f"File extension not preserved for {expected_name} (expected .{expected_ext})",
                )

            file_path = f"{download_path}/{expected_name}"
            result = execute_adb(f"shell stat -c %Y {file_path}")

            if result.success:
                try:
                    timestamp = int(result.output.strip())
                    bid_file_times[i] = {
                        "filename": expected_name,
                        "timestamp": timestamp,
                        "expected_days_ago": expected_bid["days_ago"],
                    }
                except ValueError:
                    logger.warning(
                        f"Failed to parse timestamp for {expected_name}, skipping time validation"
                    )
            else:
                logger.warning(f"Failed to get timestamp for {expected_name}: {result.error}")

        if len(bid_file_times) == 4:
            timestamps = [bid_file_times[i]["timestamp"] for i in range(1, 5)]

            for i in range(len(timestamps) - 1):
                if timestamps[i] >= timestamps[i + 1]:
                    return 0.0, (
                        f"Sequence numbers do not match creation date order! "
                        f"bid_{i + 1} timestamp ({timestamps[i]}) >= bid_{i + 2} timestamp ({timestamps[i + 1]}). "
                        f"Files should be ordered by date: earliest to latest"
                    )

        extra_bid_files = set(found_bid_files) - set(expected_new_names)
        if extra_bid_files:
            return (
                0.0,
                f"Unexpected bid_ files found (non-bid files incorrectly renamed?): {extra_bid_files}",
            )

        return 1.0, "success"
