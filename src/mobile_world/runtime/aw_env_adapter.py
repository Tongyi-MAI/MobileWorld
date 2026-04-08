"""Adapter wrapping MobileWorld's AndroidController as an AndroidWorld-compatible env."""

import contextlib
import re
import subprocess
import tempfile
import time
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


class ControllerAdapter:
    """Wraps MobileWorld's AndroidController as AndroidWorld's controller interface.

    AndroidWorld adb_utils functions call env.controller.execute_adb_call(request)
    with protobuf AdbRequest objects. This adapter translates those to raw ADB commands.
    It also provides pull_file/push_file as context managers (AW pattern).
    """

    def __init__(self, mw_controller: AndroidController):
        self._controller = mw_controller
        # Some AW code accesses env.controller.env for the raw env interface.
        # Since ControllerAdapter itself implements execute_adb_call, point back to self.
        self.env = self

    def _run_adb(self, cmd: str) -> "AdbResponse":
        """Run an ADB command with the device serial."""
        return execute_adb(f"adb -s {self._controller.device} {cmd}")

    def _run_adb_args(self, args: list[str]) -> "AdbResponse":
        """Run ADB with args as a list (avoids shell interpretation of newlines)."""
        cmd_list = ["adb", "-s", self._controller.device] + args
        try:
            result = subprocess.run(
                cmd_list, capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                return AdbResponse(
                    success=True,
                    output=result.stdout.strip(),
                    return_code=result.returncode,
                    command=" ".join(cmd_list[:4]) + "...",
                )
            return AdbResponse(
                success=False,
                error=result.stderr or "Command execution failed",
                return_code=result.returncode,
                command=" ".join(cmd_list[:4]) + "...",
            )
        except Exception as e:
            return AdbResponse(
                success=False, error=str(e), return_code=-1, command=str(cmd_list)
            )

    def _ok_response(self, output: str = "") -> "adb_pb2.AdbResponse":
        from android_env.proto import adb_pb2
        response = adb_pb2.AdbResponse()
        response.status = adb_pb2.AdbResponse.Status.OK
        response.generic.output = output.encode("utf-8", errors="replace")
        return response

    def _error_response(self, output: str = "") -> "adb_pb2.AdbResponse":
        from android_env.proto import adb_pb2
        response = adb_pb2.AdbResponse()
        response.status = adb_pb2.AdbResponse.Status.ADB_ERROR
        response.generic.output = output.encode("utf-8", errors="replace")
        return response

    def execute_adb_call(self, request) -> "adb_pb2.AdbResponse":
        """Execute an ADB call from a protobuf AdbRequest.

        Translates protobuf-typed requests (get_current_activity, tap,
        press_button, input_text, start_activity, settings, etc.) into
        raw ADB shell commands via MobileWorld's controller.
        """
        from android_env.proto import adb_pb2

        # --- Generic shell command ---
        if request.HasField("generic"):
            args = list(request.generic.args)
            # Always use list-based subprocess to avoid shell interpretation
            # issues (multiline scripts, spaces in paths, special chars).
            result = self._run_adb_args(args)
            if result.success:
                return self._ok_response(result.output)
            return self._error_response(result.error or "")

        # --- Get current activity ---
        if request.HasField("get_current_activity"):
            result = self._run_adb(
                "shell dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"
            )
            response = adb_pb2.AdbResponse()
            if result.success and result.output:
                # Parse activity from "mCurrentFocus=Window{... com.pkg/.Activity}"
                import re
                match = re.search(r'(\S+/\S+)\}', result.output)
                activity = match.group(1) if match else result.output.strip()
                response.status = adb_pb2.AdbResponse.Status.OK
                response.get_current_activity.full_activity = activity
            else:
                response.status = adb_pb2.AdbResponse.Status.ADB_ERROR
            return response

        # --- Tap screen ---
        if request.HasField("tap"):
            x, y = request.tap.x, request.tap.y
            result = self._run_adb(f"shell input tap {x} {y}")
            return self._ok_response() if result.success else self._error_response()

        # --- Press button (home, back, enter) ---
        if request.HasField("press_button"):
            button = request.press_button.button
            button_map = {
                adb_pb2.AdbRequest.PressButton.HOME: "KEYCODE_HOME",
                adb_pb2.AdbRequest.PressButton.BACK: "KEYCODE_BACK",
                adb_pb2.AdbRequest.PressButton.ENTER: "KEYCODE_ENTER",
            }
            keycode = button_map.get(button, f"KEYCODE_{button}")
            result = self._run_adb(f"shell input keyevent {keycode}")
            return self._ok_response() if result.success else self._error_response()

        # --- Input text ---
        if request.HasField("input_text"):
            text = request.input_text.text
            self._controller.text(text)
            return self._ok_response()

        # --- Start activity ---
        if request.HasField("start_activity"):
            activity = request.start_activity.full_activity
            extra_args = list(request.start_activity.extra_args) if request.start_activity.extra_args else []
            cmd = f"shell am start -n {activity}"
            if extra_args:
                cmd += " " + " ".join(extra_args)
            result = self._run_adb(cmd)
            return self._ok_response(result.output) if result.success else self._error_response(result.error or "")

        # --- Settings (put/get) ---
        if request.HasField("settings"):
            sr = request.settings
            ns_map = {0: "system", 1: "secure", 2: "global"}
            namespace = ns_map.get(sr.name_space, "system")

            if sr.HasField("put"):
                result = self._run_adb(
                    f"shell settings put {namespace} {sr.put.key} {sr.put.value}"
                )
                return self._ok_response() if result.success else self._error_response()
            elif sr.HasField("get"):
                result = self._run_adb(
                    f"shell settings get {namespace} {sr.get.key}"
                )
                response = adb_pb2.AdbResponse()
                if result.success:
                    response.status = adb_pb2.AdbResponse.Status.OK
                    response.settings.value = result.output.strip()
                else:
                    response.status = adb_pb2.AdbResponse.Status.ADB_ERROR
                return response

        # --- Package manager (list packages) ---
        if request.HasField("package_manager"):
            result = self._run_adb("shell pm list packages")
            return self._ok_response(result.output) if result.success else self._error_response()

        # --- Install APK ---
        if request.HasField("install_apk"):
            local_path = request.install_apk.filesystem.path
            result = self._run_adb(f"install -r {local_path}")
            return self._ok_response() if result.success else self._error_response()

        # --- Pull file (returns file content in response) ---
        if request.HasField("pull"):
            remote_path = request.pull.path
            response = adb_pb2.AdbResponse()
            try:
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=Path(remote_path).suffix
                )
                tmp.close()
                self._controller.pull_file(remote_path, tmp.name)
                with open(tmp.name, "rb") as f:
                    content = f.read()
                Path(tmp.name).unlink(missing_ok=True)
                response.status = adb_pb2.AdbResponse.Status.OK
                response.pull.content = content
            except Exception as e:
                logger.warning(f"Pull failed for {remote_path}: {e}")
                response.status = adb_pb2.AdbResponse.Status.ADB_ERROR
            return response

        # --- Push file ---
        if request.HasField("push"):
            response = adb_pb2.AdbResponse()
            try:
                remote_path = request.push.path
                content = request.push.content
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=Path(remote_path).suffix
                )
                tmp.write(content)
                tmp.close()
                self._controller.push_file(tmp.name, remote_path)
                Path(tmp.name).unlink(missing_ok=True)
                response.status = adb_pb2.AdbResponse.Status.OK
            except Exception as e:
                logger.warning(f"Push failed: {e}")
                response.status = adb_pb2.AdbResponse.Status.ADB_ERROR
            return response

        # --- Fallback: try to handle as generic ---
        logger.warning(f"Unsupported AdbRequest type, attempting generic handling: {request}")
        return self._error_response("unsupported request type")

    def get_ui_elements(self) -> list:
        """Get UI elements via UIAutomator XML dump.

        Used by AW's actuation code (click_element, find_and_click_element)
        during app onboarding and some task evaluations.
        """
        from android_world.env import adb_utils as aw_adb_utils
        from android_world.env import representation_utils
        xml_content = aw_adb_utils.uiautomator_dump(self)
        return representation_utils.xml_dump_to_ui_elements(xml_content)

    @contextlib.contextmanager
    def pull_file(self, remote_path: str, timeout_sec: float = None):
        """Pull a remote directory to a local temp dir, yielding the temp dir path.

        AndroidWorld expects pull_file to:
        1. Take a file path (e.g., /data/data/app/databases/events.db)
        2. Pull the ENTIRE parent directory to a local temp directory
        3. Yield the temp directory path (not the file path)

        The caller then constructs the full path:
            local_db_path = os.path.join(local_dir, "events.db")
        """
        remote_dir = str(Path(remote_path).parent)
        tmp_dir = tempfile.mkdtemp(prefix="aw_pull_")
        try:
            # Pull entire remote directory using adb pull
            result = self._run_adb_args(["pull", remote_dir + "/.", tmp_dir + "/"])
            if not result.success:
                logger.warning(f"Directory pull failed, trying single file: {result.error}")
                # Fallback: pull just the single file
                filename = Path(remote_path).name
                local_file = Path(tmp_dir) / filename
                self._controller.pull_file(remote_path, str(local_file))
            yield tmp_dir
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def push_file(self, local_path: str, remote_path: str, timeout_sec: float = None):
        """Push a local file to the device, replacing the remote directory.

        Matches AndroidWorld's push_file: clear remote dir, then push file.
        Uses AW's file_utils.copy_data_to_device which sends a Push protobuf
        request (handled by execute_adb_call above).
        """
        from android_world.utils import file_utils
        remote_dir = str(Path(remote_path).parent)
        file_utils.clear_directory(remote_dir, self)
        file_utils.copy_data_to_device(local_path, remote_path, self.env, timeout_sec)


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
        self.controller = ControllerAdapter(controller)

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

    def _try_uiautomator_dump(self) -> tuple[list, str | None]:
        """Attempt a UIAutomator XML dump. Returns (ui_elements, xml_string).

        Returns ([], None) on failure. Does NOT log at error level unless the
        XML file path is completely missing.
        """
        self._xml_counter += 1
        prefix = f"aw_state_{self._xml_counter}"
        result = self._controller.get_xml(prefix, self._temp_dir)
        if isinstance(result, AdbResponse):
            return [], None
        xml_path = Path(result)
        if not xml_path.exists():
            return [], None
        try:
            xml_content = xml_path.read_text(encoding="utf-8", errors="ignore")
            from android_world.env import representation_utils
            ui_elements = representation_utils.xml_dump_to_ui_elements(xml_content)
            return ui_elements, xml_content
        except Exception as e:
            logger.debug(f"UIAutomator parse failed: {e}")
            return [], None

    def _get_current_focus_package(self) -> str | None:
        """Return the package name of the currently-focused window via dumpsys.

        Falls back to mFocusedApp if mCurrentFocus is a transient error dialog.
        """
        result = execute_adb(
            f"adb -s {self._controller.device} shell dumpsys window"
            " | grep -E 'mCurrentFocus|mFocusedApp'"
        )
        if not result.success or not result.output:
            return None
        # Prefer mFocusedApp (the real activity) over mCurrentFocus (which
        # may be transiently holding an Application Error / ANR dialog).
        lines = result.output.splitlines()
        focused_line = next((l for l in lines if "mFocusedApp" in l), None)
        curfocus_line = next((l for l in lines if "mCurrentFocus" in l), None)

        for line in [focused_line, curfocus_line]:
            if not line:
                continue
            m = re.search(r"u0\s+([\w\.]+)/", line)
            if m and m.group(1) != "null":
                return m.group(1)
        return None

    def _a11y_forest_matches_package(self, forest, package: str) -> bool:
        """Check if a11y forest contains a window with nodes from `package`."""
        if forest is None or not package:
            return False
        for w in forest.windows:
            if not w.HasField('tree'):
                continue
            for n in w.tree.nodes:
                if n.package_name == package:
                    return True
        return False

    def get_state(self) -> State:
        """Get current UI state.

        Strategy:
          1. Dismiss the AccessibilityForwarder crash dialog if it's in
             front (known Pixel_8_API_34 APK bug — the forwarder's polling
             thread can throw NPE in getWindows()).
          2. Prefer the A11y gRPC forest because UIAutomator's `dump`
             command fails on animating screens (e.g. running stopwatch).
             Use a smart forest picker that prefers snapshots with a large
             full-screen non-system window (real foreground app), not a
             transient popup or empty buffer.
          3. Fall back to UIAutomator only if a11y is unusable. Note that
             UIAutomator implicitly displaces the forwarder's service,
             which crashes its polling thread; we request a restart after
             every UIAutomator call.

        Always returns a non-None forest — some AW evaluators call
        forest_to_ui_elements(state.forest) directly and crash on None.
        """
        from mobile_world.runtime.a11y_grpc_manager import get_manager
        mgr = get_manager()
        empty_forest = mgr.empty_forest()

        focus_package = self._get_current_focus_package()
        logger.debug(f"get_state: focus_package={focus_package}")

        # Dismiss forwarder crash dialog if present (Pixel_8_API_34 bug).
        # This dialog appears when the forwarder's polling thread throws
        # a NullPointerException in getWindows(). It covers the app, which
        # prevents us from seeing the real UI state.
        if focus_package == "com.google.androidenv.accessibilityforwarder":
            logger.warning(
                "get_state: AccessibilityForwarder crash dialog is focused;"
                " dismissing + re-enabling service"
            )
            device = self._controller.device
            execute_adb(
                f"adb -s {device} shell am force-stop"
                " com.google.androidenv.accessibilityforwarder"
            )
            time.sleep(0.5)
            # Re-enable the accessibility service so the forwarder can
            # resume capturing window state. Android re-binds it on demand
            # when the secure setting is refreshed.
            execute_adb(
                f"adb -s {device} shell settings put secure"
                " enabled_accessibility_services"
                " com.google.androidenv.accessibilityforwarder/"
                "com.google.androidenv.accessibilityforwarder."
                "AccessibilityForwarder"
            )
            execute_adb(
                f"adb -s {device} shell settings put secure"
                " accessibility_enabled 1"
            )
            # Re-configure the forwarder's target port via broadcast.
            from mobile_world.runtime.a11y_grpc_manager import get_manager as _gm
            port = _gm().port
            if port:
                execute_adb(
                    f"adb -s {device} shell am broadcast"
                    " -a accessibility_forwarder.intent.action.SET_GRPC"
                    f" --ei port {port}"
                    " -n com.google.androidenv.accessibilityforwarder/"
                    "com.google.androidenv.accessibilityforwarder."
                    "FlagsBroadcastReceiver"
                )
                execute_adb(
                    f"adb -s {device} shell am broadcast"
                    " -a accessibility_forwarder.intent.action.ENABLE_GRPC"
                    " -n com.google.androidenv.accessibilityforwarder/"
                    "com.google.androidenv.accessibilityforwarder."
                    "FlagsBroadcastReceiver"
                )
                execute_adb(
                    f"adb -s {device} shell am broadcast"
                    " -a accessibility_forwarder.intent.action."
                    "ENABLE_ACCESSIBILITY_TREE_LOGS"
                    " -n com.google.androidenv.accessibilityforwarder/"
                    "com.google.androidenv.accessibilityforwarder."
                    "FlagsBroadcastReceiver"
                )
            time.sleep(2.5)  # allow forwarder to reconnect + push a few forests
            focus_package = self._get_current_focus_package()
            logger.debug(f"get_state: post-dismiss focus_package={focus_package}")

        # --- Primary: A11y gRPC forest ---
        a11y_elements: list = []
        a11y_forest = None
        if mgr.is_running:
            a11y_elements, a11y_forest = mgr.get_ui_elements_and_forest()

        # Decide if the a11y forest is "good" — i.e. contains at least one
        # non-system window that covers most of the screen (a real app
        # window, not a popup).  Popups reported by the AW forwarder have
        # bounds like (534,279,1049,961) which is ~515x682, well under the
        # Pixel 8's 1080x2400.
        a11y_is_good = False
        if a11y_forest is not None:
            for w in a11y_forest.windows:
                wtype = getattr(w, 'window_type', 0)
                if wtype == 3:  # TYPE_SYSTEM (status/nav bar)
                    continue
                bbox = w.bounds_in_screen if w.HasField('bounds_in_screen') else None
                if bbox is None:
                    continue
                width = bbox.right - bbox.left
                height = bbox.bottom - bbox.top
                if width >= 900 and height >= 1800:
                    a11y_is_good = True
                    break

        logger.debug(
            f"get_state: a11y_is_good={a11y_is_good}, "
            f"a11y_n_elements={len(a11y_elements)}, "
            f"a11y_n_windows={len(a11y_forest.windows) if a11y_forest else 0}"
        )

        if a11y_is_good and a11y_elements:
            return State(ui_elements=a11y_elements, forest=a11y_forest or empty_forest)

        # --- Fallback: UIAutomator dump ---
        logger.debug("get_state: falling back to UIAutomator dump")
        ui_elements, xml_content = self._try_uiautomator_dump()
        logger.debug(f"get_state: UIAutomator returned {len(ui_elements)} elements")
        if ui_elements:
            # UIAutomator displaces the forwarder service, crashing its
            # polling thread. Tell the manager it needs a restart next time.
            mgr.mark_for_restart()
            return State(ui_elements=ui_elements, forest=a11y_forest or empty_forest)

        # --- Last resort: whatever a11y gave us (even if thin) ---
        if a11y_elements:
            logger.debug("get_state: last-resort using thin a11y elements")
            return State(ui_elements=a11y_elements, forest=a11y_forest or empty_forest)

        logger.warning("Both A11y and UIAutomator returned empty state")
        return State(ui_elements=[], forest=empty_forest)

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
