"""Tests for EnvAdapter that wraps AndroidController for AndroidWorld compatibility."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mobile_world.runtime.aw_env_adapter import EnvAdapter


@pytest.fixture
def mock_controller():
    """Create a mock AndroidController."""
    controller = MagicMock()
    controller.device = "emulator-5554"
    controller.width = 1080
    controller.height = 2400
    return controller


class TestEnvAdapterInit:
    def test_stores_controller(self, mock_controller):
        adapter = EnvAdapter(mock_controller)
        assert adapter._controller is mock_controller

    def test_creates_temp_dir(self, mock_controller):
        adapter = EnvAdapter(mock_controller)
        assert adapter._temp_dir is not None
        assert Path(adapter._temp_dir).exists()


class TestExecuteAdb:
    def test_bare_shell_command(self, mock_controller):
        """AW tasks pass bare shell commands like 'dumpsys battery'."""
        mock_controller.device = "emulator-5554"
        adapter = EnvAdapter(mock_controller)

        with patch("mobile_world.runtime.aw_env_adapter.execute_adb") as mock_exec:
            mock_exec.return_value = MagicMock(success=True, output="level: 100")
            result = adapter.execute_adb("dumpsys battery")
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0][0]
            assert "emulator-5554" in cmd
            assert "shell" in cmd

    def test_full_adb_command_strips_prefix(self, mock_controller):
        """AW tasks may pass full 'adb shell ...' commands."""
        adapter = EnvAdapter(mock_controller)
        with patch("mobile_world.runtime.aw_env_adapter.execute_adb") as mock_exec:
            mock_exec.return_value = MagicMock(success=True, output="ok")
            adapter.execute_adb("adb shell dumpsys battery")
            cmd = mock_exec.call_args[0][0]
            assert "-s emulator-5554" in cmd
            assert cmd.count("shell") == 1

    def test_returns_output_string(self, mock_controller):
        adapter = EnvAdapter(mock_controller)
        with patch("mobile_world.runtime.aw_env_adapter.execute_adb") as mock_exec:
            mock_exec.return_value = MagicMock(success=True, output="result_value")
            result = adapter.execute_adb("getprop ro.build.version.sdk")
            assert result == "result_value"


class TestFileOperations:
    def test_pull_file(self, mock_controller):
        mock_controller.pull_file.return_value = MagicMock(success=True, output="/local/path")
        adapter = EnvAdapter(mock_controller)
        adapter.pull_file("/sdcard/file.txt", "/tmp/file.txt")
        mock_controller.pull_file.assert_called_once_with("/sdcard/file.txt", "/tmp/file.txt")

    def test_push_file(self, mock_controller):
        mock_controller.push_file.return_value = MagicMock(success=True, output="/sdcard/file.txt")
        adapter = EnvAdapter(mock_controller)
        adapter.push_file("/tmp/file.txt", "/sdcard/file.txt")
        mock_controller.push_file.assert_called_once_with("/tmp/file.txt", "/sdcard/file.txt")


class TestGetState:
    def test_returns_state_with_ui_elements(self, mock_controller):
        """get_state() should parse UIAutomator XML into UIElement list."""
        adapter = EnvAdapter(mock_controller)

        xml_content = '<?xml version="1.0" ?><hierarchy rotation="0"><node text="Hello" resource-id="com.app/text" class="android.widget.TextView" bounds="[0,0][100,50]" /></hierarchy>'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write(xml_content)
            xml_path = f.name

        mock_controller.get_xml.return_value = xml_path

        mock_element = MagicMock()
        mock_repr = MagicMock()
        mock_repr.xml_dump_to_ui_elements.return_value = [mock_element]
        # Wire up the mock module hierarchy so `from android_world.env import representation_utils` works
        mock_env = MagicMock()
        mock_env.representation_utils = mock_repr
        with patch.dict(sys.modules, {
            "android_world": MagicMock(),
            "android_world.env": mock_env,
            "android_world.env.representation_utils": mock_repr,
        }):
            state = adapter.get_state()
            assert hasattr(state, "ui_elements")
            assert isinstance(state.ui_elements, list)
            assert len(state.ui_elements) == 1

    def test_returns_empty_state_on_xml_error(self, mock_controller):
        """If get_xml fails, return empty state."""
        adapter = EnvAdapter(mock_controller)
        from mobile_world.runtime.utils.helpers import AdbResponse
        mock_controller.get_xml.return_value = AdbResponse(success=False, error="dump failed")
        state = adapter.get_state()
        assert state.ui_elements == []


class TestAppManagement:
    def test_close_app(self, mock_controller):
        adapter = EnvAdapter(mock_controller)
        adapter.close_app("com.example.app")
        mock_controller.kill_package.assert_called_once_with("com.example.app")

    def test_launch_app(self, mock_controller):
        adapter = EnvAdapter(mock_controller)
        adapter.launch_app("com.example.app")
        mock_controller.launch_app.assert_called_once_with("com.example.app")


class TestCleanup:
    def test_cleanup_removes_temp_dir(self, mock_controller):
        adapter = EnvAdapter(mock_controller)
        temp_dir = adapter._temp_dir
        assert Path(temp_dir).exists()
        adapter.cleanup()
        assert not Path(temp_dir).exists()
