"""Adapter wrapping MobileWorld's AndroidController as an AndroidWorld-compatible env."""

import re
import tempfile
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import AdbResponse, execute_adb


@dataclass
class State:
    """Minimal state object matching what AndroidWorld tasks expect from env.get_state()."""
    ui_elements: list = field(default_factory=list)
    pixels: bytes = b""
    forest: object = None


class EnvAdapter:
    """Wraps MobileWorld's AndroidController to expose AndroidWorld's env interface.

    AndroidWorld TaskEval classes expect an env object with methods like
    execute_adb(), get_state(), pull_file(), push_file(), close_app(), and
    launch_app(). This adapter translates those calls to AndroidController.
    """

    def __init__(self, controller: AndroidController):
        self._controller = controller
        self._temp_dir = tempfile.mkdtemp(prefix="aw_env_")
        self._xml_counter = 0

    def execute_adb(self, command: str) -> str:
        """Execute an ADB command on the device.

        AndroidWorld tasks pass commands in various forms:
        - Bare shell commands: "dumpsys battery"
        - With shell prefix: "shell dumpsys battery"
        - Full ADB commands: "adb shell dumpsys battery"
        - Non-shell commands: "adb pull /sdcard/file.txt /tmp/"

        This method normalizes them all to work with the device.
        """
        device = self._controller.device
        cmd = command.strip()

        # Strip leading "adb" and any existing device flags
        cmd = re.sub(r"^adb\s+", "", cmd)
        cmd = re.sub(r"^-s\s+\S+\s+", "", cmd)  # only strip -s at start, not mid-command

        # If it doesn't start with a known ADB subcommand, assume "shell"
        adb_subcommands = {"shell", "pull", "push", "install", "uninstall", "forward",
                           "reverse", "logcat", "bugreport", "emu", "root", "remount"}
        first_word = cmd.split()[0] if cmd else ""
        if first_word not in adb_subcommands:
            cmd = f"shell {cmd}"

        full_cmd = f"adb -s {device} {cmd}"
        result = execute_adb(full_cmd)

        if result.success:
            return result.output
        else:
            logger.warning(f"ADB command failed: {full_cmd} -> {result.error}")
            return result.error or ""

    def pull_file(self, remote_path: str, local_path: str) -> None:
        """Pull a file from the device to local filesystem."""
        self._controller.pull_file(remote_path, local_path)

    def push_file(self, local_path: str, remote_path: str) -> None:
        """Push a file from local filesystem to the device."""
        self._controller.push_file(local_path, remote_path)

    def get_state(self) -> State:
        """Get current UI state with elements parsed from UIAutomator XML.

        Calls controller.get_xml() to dump the UI hierarchy, reads the XML file,
        and uses AndroidWorld's xml_dump_to_ui_elements() to parse it into
        UIElement objects.
        """
        self._xml_counter += 1
        prefix = f"aw_state_{self._xml_counter}"

        result = self._controller.get_xml(prefix, self._temp_dir)

        # get_xml returns a file path string on success, AdbResponse on failure
        if isinstance(result, AdbResponse):
            logger.warning("Failed to get UI XML for get_state()")
            return State(ui_elements=[])

        xml_path = Path(result)
        if not xml_path.exists():
            logger.warning(f"XML file not found at {xml_path}")
            return State(ui_elements=[])

        try:
            xml_content = xml_path.read_text(encoding="utf-8", errors="ignore")
            # Use AndroidWorld's own XML parser
            from android_world.env import representation_utils
            ui_elements = representation_utils.xml_dump_to_ui_elements(xml_content)
            return State(ui_elements=ui_elements)
        except ImportError:
            logger.error(
                "Could not import android_world.env.representation_utils. "
                "Ensure android_world is installed."
            )
            return State(ui_elements=[])
        except Exception as e:
            logger.error(f"Failed to parse UI XML: {e}")
            return State(ui_elements=[])

    def close_app(self, package_name: str) -> None:
        """Force-stop an app by package name."""
        self._controller.kill_package(package_name)

    def launch_app(self, app_name: str) -> None:
        """Launch an app by name."""
        self._controller.launch_app(app_name)

    def cleanup(self) -> None:
        """Remove temp directory used for XML dumps."""
        if self._temp_dir and Path(self._temp_dir).exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
