import base64
import os
import shlex
import time
from datetime import datetime

from loguru import logger

from mobile_world.runtime.utils.helpers import (
    AdbResponse,
    execute_adb,
    time_within_ten_secs,
)
from mobile_world.runtime.utils.models import APP_DICT, COMMON_APP_MAPPER

APP_LOWER_DICT = {app_name.lower(): package_name for package_name, app_name in COMMON_APP_MAPPER.items()}
APP_LOWER_DICT.update({k.lower(): v for k, v in APP_DICT.items()})


class AndroidController:
    def __init__(self, device="emulator-5554"):
        self.device = device
        self.screenshot_dir = "/sdcard"
        self.xml_dir = "/sdcard"
        self.ac_xml_dir = "/sdcard/Android/data/com.example.android.xml_parser/files"
        self.width, self.height = self.get_device_size()
        self.viewport_size = (self.width, self.height)
        self.backslash = "\\"

        self.interaction_cache = ""
        self.user_agent_chat_history = []

        # Initialize user interaction properties
        self.user_sys_prompt = None
        self.model_config = None

    def get_device_size(self):
        try:
            command = f"adb -s {self.device} shell wm size"
            result = execute_adb(command)
            if not result.success:
                raise RuntimeError("Failed to get device size for device")
            resolution = result.output.split(":")[1].strip()
            width, height = resolution.split("x")
            return int(width), int(height)
        except Exception as e:
            logger.error(f"Failed to get device size for device {self.device}: {e}")
            return None, None

    def get_screenshot(self, prefix, save_dir, try_times: int = 0) -> AdbResponse:
        remote_path = os.path.join(self.screenshot_dir, prefix + ".png").replace(
            self.backslash, "/"
        )
        local_path = os.path.join(save_dir, prefix + ".png")

        # try the stealth API first, otherwise screenshot
        # may trigger events in some apps
        stealth_command = f"adb -s {self.device} exec-out screencap -p > {local_path}"
        stealth_result = execute_adb(stealth_command)
        if stealth_result.success:
            return AdbResponse(success=True, output=local_path, command=stealth_command)

        cap_command = f"adb -s {self.device} shell screencap -p {remote_path}"
        pull_command = f"adb -s {self.device} pull {remote_path} {local_path}"
        rm_command = f"adb -s {self.device} shell rm {remote_path}"

        cap_result = execute_adb(cap_command)
        if cap_result.success:
            result = execute_adb(pull_command)

            if not result.success and try_times > 0:
                # occasionally the pull command fails at file not found, so we try again, likely due to file not finished being written yet
                time.sleep(1)
                return self.get_screenshot(prefix, save_dir, try_times - 1)
            elif not result.success and try_times <= 0:
                execute_adb(rm_command, output=False)
                return AdbResponse(
                    success=False, error=result.error + cap_result.output, command=pull_command
                )
            else:
                execute_adb(rm_command, output=False)
                return AdbResponse(success=True, output=local_path, command=pull_command)
        return cap_result

    def get_xml(self, prefix, save_dir):
        remote_path = os.path.join(self.xml_dir, prefix + ".xml").replace(self.backslash, "/")
        local_path = os.path.join(save_dir, prefix + ".xml")
        dump_command = f"adb -s {self.device} shell uiautomator dump {remote_path}"
        pull_command = f"adb -s {self.device} pull {remote_path} {local_path}"

        def is_file_empty(file_path):
            return os.path.exists(file_path) and os.path.getsize(file_path) == 0

        for attempt in range(5):
            result = execute_adb(dump_command)
            if not result.success:
                time.sleep(2)
                continue

            result = execute_adb(pull_command)
            if not result.success or is_file_empty(local_path):
                time.sleep(2)
                continue
            return local_path

        # Final attempt after 3 retries
        result = execute_adb(dump_command)
        result = execute_adb(pull_command)
        if result.success and not is_file_empty(local_path):
            return local_path

        return result

    def get_ac_xml(self, prefix, save_dir):
        remote_path = f"{os.path.join(self.ac_xml_dir, 'ui.xml').replace(self.backslash, '/')}"
        local_path = os.path.join(save_dir, prefix + ".xml")
        pull_command = f"adb -s {self.device} pull {remote_path} {local_path}"

        def is_file_empty(file_path):
            return os.path.exists(file_path) and os.path.getsize(file_path) == 0

        for _ in range(5):
            result = execute_adb(pull_command)
            if result.success and not is_file_empty(local_path):
                return local_path
            time.sleep(2)

        # Final attempt after 3 retries
        result = execute_adb(pull_command)
        if result.success and not is_file_empty(local_path):
            return local_path

        return result

    def get_current_activity(self):
        adb_command = "adb -s {device} shell dumpsys window | grep mCurrentFocus | awk -F '/' '{print $1}' | awk '{print $NF}'"
        adb_command = adb_command.replace("{device}", self.device)
        result = execute_adb(adb_command)
        if result.success:
            return result.output
        return 0

    def get_current_app(self):
        activity = self.get_current_activity()
        app = activity.split(".")[-1]
        if not app:
            return ""
        return app

    def back(self) -> AdbResponse:
        adb_command = f"adb -s {self.device} shell input keyevent KEYCODE_BACK"
        ret = execute_adb(adb_command)
        return ret

    def enter(self) -> AdbResponse:
        adb_command = f"adb -s {self.device} shell input keyevent KEYCODE_ENTER"
        ret = execute_adb(adb_command)
        return ret

    def home(self) -> AdbResponse:
        adb_command = f"adb -s {self.device} shell input keyevent KEYCODE_HOME"
        ret = execute_adb(adb_command)
        return ret

    def app_switch(self) -> AdbResponse:
        adb_command = f"adb -s {self.device} shell input keyevent KEYCODE_APP_SWITCH"
        ret = execute_adb(adb_command)
        return ret

    def tap(self, x: int, y: int) -> AdbResponse:
        adb_command = f"adb -s {self.device} shell input tap {x} {y}"
        ret = execute_adb(adb_command)
        return ret

    def double_tap(self, x: int, y: int) -> AdbResponse:
        ret = self.tap(x, y)
        time.sleep(0.1)
        ret = self.tap(x, y)
        return ret

    def text(self, input_str: str) -> AdbResponse:
        chars = input_str
        charsb64 = str(base64.b64encode(chars.encode("utf-8")))[1:]
        adb_command = (
            f"adb -s {self.device} shell am broadcast -a ADB_INPUT_B64 --es msg {charsb64}"
        )
        ret = execute_adb(adb_command)
        return ret

    def simulate_sms(self, sender: str | None, message: str | None) -> AdbResponse:
        if sender is None or message is None:
            return AdbResponse(
                success=False,
                error="sender and message must not be None",
                command=f"adb -s {self.device} emu sms send",
            )
        adb_command = f"adb -s {self.device} emu sms send {shlex.quote(str(sender))} {shlex.quote(str(message))}"
        ret = execute_adb(adb_command)
        logger.info(f"simulate_sms command: {adb_command}")
        return ret

    def long_press(self, x: int, y: int, duration: int = 1000) -> AdbResponse:
        adb_command = f"adb -s {self.device} shell input swipe {x} {y} {x} {y} {duration}"
        ret = execute_adb(adb_command)
        return ret

    def kill_package(self, package_name: str) -> AdbResponse:
        command = f"adb -s {self.device} shell am force-stop {package_name}"
        return execute_adb(command)

    def swipe(
        self,
        x: int | None,
        y: int | None,
        direction: str,
    ) -> AdbResponse:
        if self.width is None or self.height is None:
            # attempt to get device size again
            self.width, self.height = self.get_device_size()
        if x is None:
            x = self.width // 2
        if y is None:
            y = self.height // 2

        unit_dist = int(self.width / 10)
        unit_dist *= 2
        if direction == "up":
            offset = 0, -2 * unit_dist
        elif direction == "down":
            offset = 0, 2 * unit_dist
        elif direction == "left":
            offset = -1 * unit_dist, 0
        elif direction == "right":
            offset = unit_dist, 0
        else:
            return AdbResponse(
                success=False,
                error=f"Invalid direction: {direction}. Must be one of: up, down, left, right",
                command=f"adb -s {self.device} shell input swipe",
            )
        duration = 400
        adb_command = f"adb -s {self.device} shell input swipe {x} {y} {x + offset[0]} {y + offset[1]} {duration}"
        ret = execute_adb(adb_command)
        return ret

    def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration: int = 400
    ) -> AdbResponse:
        adb_command = (
            f"adb -s {self.device} shell input swipe {start_x} {start_y} {end_x} {end_y} {duration}"
        )
        ret = execute_adb(adb_command)
        return ret

    def launch_app(self, app_name: str) -> AdbResponse:
        command = ""

        if app_name is not None and app_name.lower() in APP_LOWER_DICT:
            command = f"adb -s {self.device} shell monkey -p {APP_LOWER_DICT[app_name.lower()]} -c android.intent.category.LAUNCHER 1"
            ret = execute_adb(command)
            if ret.success:
                return ret
        logger.warning(
            f"Failed to launch the app: {app_name}. Available app list: {list(APP_LOWER_DICT.keys())}"
        )
        return AdbResponse(
            success=False,
            error=f"Failed to launch the app: {app_name}",
            command=command,
        )

    def answer(self, answer_str: str) -> None:
        self.interaction_cache = answer_str

    def ask_user(self, agent_question: str) -> str:
        """
        Ask the user a question using a simulated user agent.

        Args:
            agent_question: The question to ask the user

        Returns:
            The user's answer as a string

        Raises:
            RuntimeError: If user_sys_prompt or model_config is not configured
        """
        from mobile_world.tasks.utils import user_agent_answer_question

        if self.user_sys_prompt is None:
            logger.error(
                "user_sys_prompt is not configured. Task must set it during initialization."
            )
            raise RuntimeError(
                "user_sys_prompt is not configured. Please initialize the task first."
            )

        if self.model_config is None:
            logger.error("model_config is not configured. Task must set it during initialization.")
            raise RuntimeError("model_config is not configured. Please initialize the task first.")

        logger.info(f"[ASK_USER] Agent question: {agent_question}")
        user_answer = user_agent_answer_question(
            self.user_sys_prompt, agent_question, self.model_config, self.user_agent_chat_history
        )
        self.user_agent_chat_history.append({"role": "user", "content": agent_question})
        self.user_agent_chat_history.append({"role": "assistant", "content": user_answer})
        logger.info(f"[ASK_USER] User answer: {user_answer}")
        return user_answer

    def check_ac_survive(self):
        try:
            time_command = f"adb -s {self.device} shell stat -c %y /sdcard/Android/data/com.example.android.xml_parser/files/ui.xml"
            time_phone_command = f'adb -s {self.device} shell date +"%H:%M:%S"'
            result = time_within_ten_secs(
                execute_adb(time_command),
                execute_adb(time_phone_command),
            )
        except Exception as e:
            print(e)
            return False
        return result

    def list_snapshots(self):
        """List all available snapshots for the emulator"""
        try:
            adb_command = f"adb -s {self.device} emu avd snapshot list"
            result = execute_adb(adb_command)

            if not result.success:
                logger.error(f"Failed to list snapshots: {result.error}")
                return []

            # Parse snapshot names from response
            snapshots = []
            lines = result.output.split("\n")
            for line in lines:
                line = line.strip()
                if line and not line.startswith("OK") and line != "":
                    snapshots.append(line)

            return snapshots
        except Exception as e:
            logger.error(f"Failed to list snapshots: {e}")
            return []

    def delete_snapshot(self, tag):
        """Delete a snapshot with the given tag"""
        try:
            adb_command = f"adb -s {self.device} emu avd snapshot delete {tag}"
            result = execute_adb(adb_command)

            if result.success and "OK" in result.output:
                logger.info(f"Successfully deleted snapshot: {tag}")
                return True
            else:
                logger.error(
                    f"Failed to delete snapshot {tag}: {result.error if not result.success else result.output}"
                )
                return False
        except Exception as e:
            logger.error(f"Failed to delete snapshot {tag}: {e}")
            return False

    def create_snapshot(self, tag=None):
        """Create a snapshot with optional tag name"""
        try:
            if tag is None:
                tag = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            adb_command = f"adb -s {self.device} emu avd snapshot save {tag}"
            result = execute_adb(adb_command)

            if result.success and "OK" in result.output:
                logger.info(f"Successfully created snapshot: {tag}")
                return tag
            else:
                logger.error(
                    f"Failed to create snapshot {tag}: {result.error if not result.success else result.output}"
                )
                return False
        except Exception as e:
            logger.error(f"Failed to create snapshot: {e}")
            return False

    def load_snapshot(self, tag):
        """Load a snapshot with the given tag"""
        try:
            adb_command = f"adb -s {self.device} emu avd snapshot load {tag}"
            result = execute_adb(adb_command)

            if result.success and "OK" in result.output:
                logger.info(f"Successfully loaded snapshot: {tag}")
                # Wait a moment for the snapshot to fully load
                time.sleep(3)
                return True
            else:
                logger.error(
                    f"Failed to load snapshot {tag}: {result.error if not result.success else result.output}"
                )
                return False
        except Exception as e:
            logger.error(f"Failed to load snapshot {tag}: {e}")
            return False

    def activate_adb_keyboard(self):
        execute_adb("adb shell ime set com.android.adbkeyboard/.AdbIME")

    def check_health(self, try_times: int = 0) -> bool:
        try:
            adb_command = f"adb -s {self.device} shell getprop sys.boot_completed"
            result = execute_adb(adb_command, output=False)

            if not result.success or not result.output:
                logger.error(f"Health check failed for device {self.device}: {result.error}")
                if try_times > 0:
                    time.sleep(3)
                    return self.check_health(try_times - 1)
                else:
                    return False

            # Boot completed should return "1"
            if result.output.strip() == "1":
                return True

            return False
        except Exception as e:
            logger.error(f"Health check failed for device {self.device}: {e}")
            return False

    def push_file(self, local_path: str, remote_path: str) -> AdbResponse:
        """
        Push a file from local system to Android device.

        Args:
            local_path: Path to the local file
            remote_path: Destination path on the Android device

        Returns:
            AdbResponse with remote_path in output if successful
        """
        push_command = f'adb -s {self.device} push "{local_path}" "{remote_path}"'
        result = execute_adb(push_command)

        if result.success:
            logger.info(f"Successfully pushed file: {local_path} -> {remote_path}")
            result.output = remote_path
            return result
        else:
            logger.error(
                f"Failed to push file: {local_path} -> {remote_path}. Error: {result.error}"
            )
            return result

    def pull_file(self, remote_path: str, local_path: str) -> AdbResponse:
        """
        Pull a file from Android device to local system.

        Args:
            remote_path: Path to the file on the Android device
            local_path: Destination path on the local system

        Returns:
            AdbResponse with local_path in output if successful
        """
        pull_command = f'adb -s {self.device} pull "{remote_path}" "{local_path}"'
        result = execute_adb(pull_command)

        if result.success:
            logger.info(f"Successfully pulled file: {remote_path} -> {local_path}")
            result.output = local_path
            return result
        else:
            logger.error(
                f"Failed to pull file: {remote_path} -> {local_path}. Error: {result.error}"
            )
            return result

    def remove_file(self, remote_path: str) -> AdbResponse:
        """
        Remove a file from Android device.

        Args:
            remote_path: Path to the file on the Android device

        Returns:
            Result of the command execution
        """
        remove_command = f"adb -s {self.device} shell rm {remote_path}"
        result = execute_adb(remove_command)

        if result.success:
            logger.info(f"Successfully removed file: {remote_path}")
        else:
            logger.error(f"Failed to remove file: {remote_path}. Error: {result.error}")

        return result

    def refresh_media_scan(self, file_path):
        """
        Trigger media scanner to recognize a new file.

        Args:
            file_path: Path to the file on the Android device

        Returns:
            Result of the command execution
        """
        scan_command = (
            f"adb -s {self.device} shell am broadcast "
            f"-a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
            f"-d file://{file_path}"
        )
        result = execute_adb(scan_command)

        if result.success:
            logger.info(f"Successfully triggered media scan for: {file_path}")
        else:
            logger.warning(f"Failed to trigger media scan for: {file_path}. Error: {result.error}")

        return result


if __name__ == "__main__":
    And = AndroidController("emulator-5554")

    activity = And.get_current_activity()
    print(activity)

    app = And.get_current_app()
    print(app)
