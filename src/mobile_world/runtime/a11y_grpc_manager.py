"""Manages the A11y gRPC server for receiving accessibility trees from the emulator.

Standalone version of android_env's A11yGrpcWrapper, adapted for MobileWorld's
ControllerAdapter.  Runs a gRPC server inside the container, installs the
AccessibilityForwarder APK, and exposes `get_ui_elements_and_forest()` which returns
AndroidWorld-compatible UIElement objects.
"""

import threading
import time
from concurrent import futures
from pathlib import Path

import grpc
from loguru import logger

from android_env.components.a11y import a11y_servicer
from android_env.proto.a11y import a11y_pb2_grpc
from android_world.env import representation_utils

# Singleton: one gRPC server per process (shared across task runs).
_manager_instance = None
_manager_lock = threading.Lock()

_A11Y_PKG = "com.google.androidenv.accessibilityforwarder"
_A11Y_SERVICE = f"{_A11Y_PKG}/{_A11Y_PKG}.AccessibilityForwarder"
_A11Y_RECEIVER = f"{_A11Y_PKG}/{_A11Y_PKG}.FlagsBroadcastReceiver"

# Path inside the container where the APK is shipped.
_APK_PATH_IN_CONTAINER = "/app/docker/apks/accessibility_forwarder.apk"


class A11yGrpcManager:
    """Manages a gRPC server that receives accessibility trees from the device."""

    def __init__(self):
        self._port = None
        self._server = None
        self._servicer = None
        self._started = False
        # When True, setup_device() should force-restart the forwarder next
        # time it's called (because a previous action probably crashed the
        # forwarder's polling thread — e.g. a uiautomator dump).
        self._needs_restart = False
        # Cache of the most recent "good" forest — one that contained a
        # full-screen non-system window. Used as a fallback when the
        # forwarder's polling thread crashes and starts returning empty
        # forests, which happens reliably on Pixel_8_API_34.
        self._last_good_forest = None
        self._last_good_forest_time = 0.0

    def start_server(self) -> int:
        """Start the gRPC server. Returns the port number."""
        if self._started:
            return self._port

        import portpicker
        self._port = portpicker.pick_unused_port()
        # Keep ALL recent forests (not just latest) so we can pick the best
        # one when get_state() is called. Otherwise rapid window transitions
        # (e.g., Clock app momentarily showing its overflow menu) can cause
        # us to sample a transient, incomplete forest.
        self._servicer = a11y_servicer.A11yServicer(latest_forest_only=False)

        # Wrap _process_forest to track receipt count AND cache the most
        # recent "good" forest (one with a full-screen app window). This
        # gives us a fallback when the forwarder's polling thread crashes.
        self._forest_count = 0
        orig_process_forest = self._servicer._process_forest
        def counting_process(forest):
            self._forest_count += 1
            n_win = len(forest.windows)

            # Cache last-known-good forest.
            if self._forest_is_good(forest):
                import copy
                self._last_good_forest = copy.deepcopy(forest)
                self._last_good_forest_time = time.time()

            # Log every 25 forests with detailed window/node info for debugging.
            if self._forest_count <= 3 or self._forest_count % 25 == 0:
                summary = []
                for w in forest.windows:
                    n_nodes = len(w.tree.nodes) if w.HasField('tree') else 0
                    wtype = getattr(w, 'window_type', 0)
                    wid = getattr(w, 'id', '?')
                    bbox = w.bounds_in_screen if w.HasField('bounds_in_screen') else None
                    bstr = f"({bbox.left},{bbox.top},{bbox.right},{bbox.bottom})" if bbox else "?"
                    # Extract content_description from each node
                    cds = []
                    if w.HasField('tree'):
                        for n in w.tree.nodes:
                            cd = (n.content_description or n.text or '').strip()
                            if cd:
                                cds.append(cd[:30])
                    summary.append(f"id={wid} type={wtype} nodes={n_nodes} bounds={bstr} cds={cds[:8]}")
                logger.debug(
                    f"A11y forest #{self._forest_count} (paused={self._servicer._paused}, n_win={n_win}): "
                    + " | ".join(summary)
                )
            orig_process_forest(forest)
        self._servicer._process_forest = counting_process

        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        a11y_pb2_grpc.add_A11yServiceServicer_to_server(
            self._servicer, self._server
        )
        # Use insecure port — local_server_credentials may reject the
        # emulator's TCP connection since it goes through QEMU's NAT.
        # The forwarder doesn't actually use TLS so insecure works fine.
        self._server.add_insecure_port(f"[::]:{self._port}")
        self._server.start()
        self._started = True
        logger.info(f"A11y gRPC server started on port {self._port}")
        return self._port

    def setup_device(self, controller_adapter) -> bool:
        """Install the APK, enable the service, and configure gRPC on the device.

        Args:
            controller_adapter: ControllerAdapter instance with execute_adb_call.

        Returns:
            True if setup succeeded.
        """
        if not self._started:
            self.start_server()

        device = controller_adapter._controller.device
        adb = f"adb -s {device}"

        from mobile_world.runtime.utils.helpers import execute_adb

        # 1. Install APK if not already installed.
        result = execute_adb(f"{adb} shell pm list packages {_A11Y_PKG}")
        if _A11Y_PKG not in (result.output or ""):
            if Path(_APK_PATH_IN_CONTAINER).exists():
                logger.info("Installing accessibility forwarder APK...")
                res = execute_adb(f"{adb} install -r {_APK_PATH_IN_CONTAINER}")
                if not res.success:
                    logger.error(f"Failed to install a11y forwarder: {res.error}")
                    return False
                time.sleep(3)
            else:
                logger.warning(
                    f"A11y forwarder APK not found at {_APK_PATH_IN_CONTAINER}"
                )
                return False

        # 2. Force-restart the AccessibilityForwarder process.
        # After snapshot load, the OLD forwarder process (from before snapshot)
        # is still running with a stale gRPC port. We must kill it so a fresh
        # process starts when we re-enable the accessibility service.
        execute_adb(f"{adb} shell am force-stop {_A11Y_PKG}")
        time.sleep(1)
        execute_adb(
            f"{adb} shell settings delete secure enabled_accessibility_services"
        )
        time.sleep(1)
        execute_adb(
            f"{adb} shell settings put secure enabled_accessibility_services"
            f" {_A11Y_SERVICE}"
        )
        execute_adb(
            f"{adb} shell settings put secure accessibility_enabled 1"
        )
        time.sleep(3)

        # 3. Enable accessibility tree logging.
        execute_adb(
            f'{adb} shell am broadcast'
            f' -a accessibility_forwarder.intent.action.ENABLE_ACCESSIBILITY_TREE_LOGS'
            f' -n {_A11Y_RECEIVER}'
        )
        time.sleep(1)

        # 4. Enable gRPC forwarding.
        execute_adb(
            f'{adb} shell am broadcast'
            f' -a accessibility_forwarder.intent.action.ENABLE_GRPC'
            f' -n {_A11Y_RECEIVER}'
        )
        time.sleep(1)

        # 5. Configure no_proxy so the forwarder can reach 10.0.2.2:<port>
        #    without going through any HTTP proxy. Required for the gRPC
        #    connection to work — matches official A11yGrpcWrapper._configure_grpc.
        execute_adb(
            f'{adb} shell settings put global http_proxy :0'
        )
        execute_adb(
            f'{adb} shell settings put global no_proxy "10.0.2.2:{self._port}"'
        )

        # 6. Ensure networking is enabled (turn off airplane mode, enable wifi).
        execute_adb(f'{adb} shell settings put global airplane_mode_on 0')
        execute_adb(f'{adb} shell svc wifi enable')
        time.sleep(1)

        # 7. Configure the gRPC port — the forwarder connects to 10.0.2.2:<port>
        #    (10.0.2.2 is the Android emulator's alias for the host machine).
        execute_adb(
            f'{adb} shell am broadcast'
            f' -a "accessibility_forwarder.intent.action.SET_GRPC"'
            f' --ei "port" {self._port}'
            f' -n {_A11Y_RECEIVER}'
        )
        time.sleep(2)

        # Resume the servicer so it starts collecting forests.
        # A11yServicer starts in paused state and discards all data until resume().
        self._servicer.pause_and_clear()  # discard any stale data
        # Reset the last-good forest cache — we don't want data from a
        # prior task leaking into the current one.
        self._last_good_forest = None
        self._last_good_forest_time = 0.0
        self._servicer.resume()

        logger.info(
            f"A11y forwarder configured: device={device}, port={self._port}"
        )
        return True

    def _forest_is_good(self, forest) -> bool:
        """Return True if `forest` contains a full-screen non-system window.

        A "good" forest has at least one TYPE_APPLICATION / TYPE_INPUT_METHOD
        window whose bounds cover most of the screen (>= 900x1800 on the
        Pixel 8). This filters out:
          - empty forests (forwarder crashed)
          - system-bar-only forests
          - small popup/dropdown/tooltip windows (e.g. the Clock app's
            overflow menu which the forwarder sometimes returns stale)
        """
        for w in forest.windows:
            wtype = getattr(w, 'window_type', 0)
            if wtype == 3:  # TYPE_SYSTEM
                continue
            bbox = w.bounds_in_screen if w.HasField('bounds_in_screen') else None
            if bbox is None:
                continue
            width = bbox.right - bbox.left
            height = bbox.bottom - bbox.top
            n_nodes = len(w.tree.nodes) if w.HasField('tree') else 0
            if width >= 900 and height >= 1800 and n_nodes >= 5:
                return True
        return False

    def _forest_score(self, forest) -> int:
        """Score a forest to pick the "best" one for get_state().

        Returns the total number of nodes in NON-system-bar windows.  The
        forwarder sometimes transiently returns a forest containing only
        a tiny popup or an empty window, while the real foreground app
        window is momentarily missing.  We prefer forests whose app-window
        content is richest.
        """
        score = 0
        for w in forest.windows:
            wtype = getattr(w, 'window_type', 0)
            # type 3 is TYPE_SYSTEM (status bar / nav bar) — exclude from score.
            if wtype == 3:
                continue
            if w.HasField('tree'):
                score += len(w.tree.nodes)
        return score

    def get_ui_elements_and_forest(self) -> tuple[list, object | None]:
        """Get UI elements and raw forest from the latest accessibility tree.

        Returns:
            Tuple of (ui_elements, forest). ui_elements is empty list if unavailable.
        """
        if not self._servicer:
            return [], None

        # Collect any forests that arrived recently plus any queued.
        forests: list = self._servicer.gather_forests()
        deadline = time.time() + 0.8
        while time.time() < deadline:
            time.sleep(0.15)
            new = self._servicer.gather_forests()
            if new:
                forests.extend(new)

        # First preference: a "good" forest from the current batch (most
        # recent one with a full-screen app window).
        forest = None
        good_idx = -1
        for i in range(len(forests) - 1, -1, -1):
            if self._forest_is_good(forests[i]):
                forest = forests[i]
                good_idx = i
                break

        if forest is not None:
            logger.debug(
                f"A11y gRPC: picked good forest {good_idx+1}/{len(forests)} "
                f"from current batch"
            )
        elif self._last_good_forest is not None:
            # Fall back to the cached last-known-good forest. This is
            # reliable when the forwarder has crashed and is returning
            # empty forests.
            age = time.time() - self._last_good_forest_time
            forest = self._last_good_forest
            logger.debug(
                f"A11y gRPC: using CACHED last-good forest (age={age:.1f}s)"
            )
        elif forests:
            # Last resort: pick the highest-scoring forest from the batch.
            best_idx = 0
            best_score = -1
            for i, f in enumerate(forests):
                s = self._forest_score(f)
                if s >= best_score:
                    best_score = s
                    best_idx = i
            forest = forests[best_idx]
            logger.debug(
                f"A11y gRPC: fallback to highest-score forest {best_idx+1}/{len(forests)} "
                f"(score={best_score})"
            )
        else:
            logger.debug("A11y gRPC: no forests available")
            return [], None
        try:
            # exclude_invisible_elements=False matches official AW behavior:
            # contacts.py and other evaluators don't filter by visibility either,
            # and many Clock/timer elements are marked invisible by the system
            # but still need to be detected.
            ui_elements = representation_utils.forest_to_ui_elements(
                forest, exclude_invisible_elements=False
            )
            cds = [el.content_description for el in ui_elements if el.content_description]
            texts = [el.text for el in ui_elements if el.text]
            # Dump per-window detail to understand what the eval received.
            win_summary = []
            for w in forest.windows:
                n_nodes = len(w.tree.nodes) if w.HasField('tree') else 0
                wid = getattr(w, 'id', '?')
                wtype = getattr(w, 'window_type', 0)
                w_cds = []
                if w.HasField('tree'):
                    for n in w.tree.nodes:
                        v = (n.content_description or n.text or '').strip()
                        if v:
                            w_cds.append(v[:20])
                win_summary.append(f"id={wid} type={wtype} nodes={n_nodes} cds={w_cds[:6]}")
            logger.debug(
                f"A11y gRPC GET_STATE: {len(forest.windows)} windows, "
                f"{len(ui_elements)} UI elements, "
                f"cds[:10]={cds[:10]}, texts[:10]={texts[:10]} | "
                f"windows: {' | '.join(win_summary)}"
            )
            return ui_elements, forest
        except Exception as e:
            logger.warning(f"Failed to parse a11y forest: {e}")
            return [], None

    @staticmethod
    def empty_forest():
        """Return an empty AndroidAccessibilityForest proto.

        Used as a placeholder when A11y gRPC has no data, so that downstream
        code calling forest.windows doesn't crash on None.
        """
        from android_env.proto.a11y import android_accessibility_forest_pb2
        return android_accessibility_forest_pb2.AndroidAccessibilityForest()

    def mark_for_restart(self) -> None:
        """Request the forwarder be restarted on the next setup_device call.

        Call this after any operation that might have crashed the APK's
        polling thread (e.g. a uiautomator dump which displaces the
        accessibility service temporarily).
        """
        self._needs_restart = True

    @property
    def port(self) -> int | None:
        return self._port

    @property
    def is_running(self) -> bool:
        return self._started

    def stop(self):
        if self._server:
            self._server.stop(None)
            self._started = False
            logger.info("A11y gRPC server stopped")


def get_manager() -> A11yGrpcManager:
    """Get or create the singleton A11yGrpcManager."""
    global _manager_instance
    with _manager_lock:
        if _manager_instance is None:
            _manager_instance = A11yGrpcManager()
        return _manager_instance
