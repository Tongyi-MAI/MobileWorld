"""Tests for server suite family switching with android_world support."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestInitializeSuiteFamily:
    def test_mobile_world_creates_task_registry(self):
        with patch("mobile_world.core.server.TaskRegistry") as MockTR:
            from mobile_world.core.server import initialize_suite_family
            initialize_suite_family("mobile_world")
            MockTR.assert_called_once()

    def test_android_world_creates_aw_registry(self):
        with patch("mobile_world.core.server.AWTaskRegistry") as MockAWR:
            from mobile_world.core.server import initialize_suite_family
            initialize_suite_family("android_world")
            MockAWR.assert_called_once_with(seed=None)

    def test_android_world_with_seed(self):
        with patch("mobile_world.core.server.AWTaskRegistry") as MockAWR:
            from mobile_world.core.server import initialize_suite_family
            initialize_suite_family("android_world", seed=42)
            MockAWR.assert_called_once_with(seed=42)

    def test_mobile_world_with_seed_raises(self):
        from mobile_world.core.server import initialize_suite_family
        with pytest.raises(ValueError, match="not supported"):
            initialize_suite_family("mobile_world", seed=42)


class TestSwitchEndpointValidation:
    def test_rejects_invalid_family(self):
        from mobile_world.core.server import app
        client = TestClient(app)
        response = client.post(
            "/suite_family/switch",
            params={"target_family": "invalid_family"},
        )
        assert response.status_code == 400
