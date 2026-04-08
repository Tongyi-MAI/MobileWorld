"""Comprehensive AndroidWorld app setup for MobileWorld containers.

Installs all required APKs, runs onboarding, grants permissions, and verifies
each app individually. Designed to be robust against UI differences between
MobileWorld's Pixel 8 API 34 emulator and AndroidWorld's expected Pixel 6 API 33.
"""

import subprocess
import sys
import time
import traceback

# ---------------------------------------------------------------------------
# Expected third-party packages (need APK install)
# ---------------------------------------------------------------------------
THIRD_PARTY_PACKAGES = {
    "android world": "com.example.androidworld",
    "audio recorder": "com.dimowner.audiorecorder",
    "clipper": "ca.zgrs.clipper",
    "simple calendar pro": "com.simplemobiletools.calendar.pro",
    "tasks": "org.tasks",
    "simple draw pro": "com.simplemobiletools.draw.pro",
    "simple gallery pro": "com.simplemobiletools.gallery.pro",
    "simple sms messenger": "com.simplemobiletools.smsmessenger",
    "miniwob": "com.google.androidenv.miniwob",
    "pro expense": "com.arduia.expense",
    "broccoli app": "com.flauschcode.broccoli",
    "osmand": "net.osmand",
    "open tracks sports tracker": "de.dennisguse.opentracks",
    "vlc": "org.videolan.vlc",
    "joplin": "net.cozic.joplin",
    "retro music": "code.name.monkey.retromusic",
    "markor": "net.gsantner.markor",
}

# Pre-installed apps (no APK needed, just onboarding)
PREINSTALLED_PACKAGES = {
    "camera": "com.android.camera2",
    "chrome": "com.android.chrome",
    "clock": "com.google.android.deskclock",
    "contacts": "com.google.android.contacts",
    "dialer": "com.google.android.dialer",
    "files": "com.google.android.documentsui",
    "settings": "com.android.settings",
}


def adb(*args: str) -> str:
    """Run an ADB command and return stdout."""
    cmd = ["adb"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.stdout.strip()


def adb_shell(*args: str) -> str:
    """Run an ADB shell command."""
    return adb("shell", *args)


def get_installed_packages() -> set[str]:
    """Get set of installed package names via raw ADB."""
    output = adb_shell("pm", "list", "packages")
    packages = set()
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            packages.add(line[len("package:"):])
    return packages


def grant_permission(package: str, permission: str):
    """Grant a permission to a package."""
    adb_shell("pm", "grant", package, permission)


def clear_app_data(package: str):
    """Clear app data."""
    adb_shell("pm", "clear", package)


def force_stop(package: str):
    """Force stop an app."""
    adb_shell("am", "force-stop", package)


def launch_activity(activity: str):
    """Launch an activity."""
    adb_shell("am", "start", "-n", activity)


def press_home():
    """Press home button."""
    adb_shell("input", "keyevent", "KEYCODE_HOME")


def tap(x: int, y: int):
    """Tap at screen coordinates."""
    adb_shell("input", "tap", str(x), str(y))


def set_default_sms_app(package: str):
    """Set default SMS app via settings."""
    adb_shell(
        "settings", "put", "secure",
        "sms_default_application", package
    )


def monkey_launch(package: str):
    """Launch app via monkey (triggers full first-launch flow)."""
    adb_shell(
        "monkey", "-p", package,
        "-c", "android.intent.category.LAUNCHER", "1"
    )


def appops_set(package: str, op: str, value: str):
    """Set appops permission."""
    adb_shell("appops", "set", package, op, value)


def check_dir_exists(path: str) -> bool:
    """Check if directory exists on device."""
    result = adb_shell("test", "-d", path, "&&", "echo", "yes", "||", "echo", "no")
    return "yes" in result


def mkdir(path: str):
    """Create directory on device."""
    adb_shell("mkdir", "-p", path)


# ---------------------------------------------------------------------------
# Per-app setup functions using raw ADB (no protobuf adapter needed)
# ---------------------------------------------------------------------------

def setup_camera():
    """Camera: grant location, click through onboarding."""
    pkg = "com.android.camera2"
    clear_app_data(pkg)
    grant_permission(pkg, "android.permission.ACCESS_COARSE_LOCATION")
    launch_activity("com.android.camera2/com.android.camera.CameraLauncher")
    time.sleep(3)
    # Try clicking NEXT button - coordinates for typical onboarding
    _try_click_element_via_adapter("camera", "NEXT")
    time.sleep(1)
    force_stop(pkg)


def setup_chrome():
    """Chrome: clear data, skip onboarding screens."""
    pkg = "com.android.chrome"
    clear_app_data(pkg)
    launch_activity(
        "com.android.chrome/com.google.android.apps.chrome.Main"
    )
    time.sleep(3)
    # Try automated onboarding via adapter
    success = _try_click_element_via_adapter("chrome", "Accept & continue")
    if success:
        time.sleep(2)
        _try_click_element_via_adapter("chrome", "No thanks")
        time.sleep(2)
        _try_click_element_via_adapter("chrome", "No thanks")
    else:
        # Fallback: just accept whatever is on screen and close
        print("  Chrome onboarding: automated click failed, trying fallback...")
        # On newer Chrome, might use different text
        _try_click_element_via_adapter("chrome", "Accept and continue")
        time.sleep(2)
        _try_click_element_via_adapter("chrome", "No Thanks")
        time.sleep(2)
        _try_click_element_via_adapter("chrome", "No Thanks")
    time.sleep(1)
    force_stop(pkg)


def setup_clock():
    """Clock: just open and close for tooltip display."""
    pkg = "com.google.android.deskclock"
    clear_app_data(pkg)
    launch_activity(
        "com.google.android.deskclock/com.android.deskclock.DeskClock"
    )
    time.sleep(3)
    force_stop(pkg)


def setup_contacts():
    """Contacts: clear data, skip backup/notification screens."""
    pkg = "com.google.android.contacts"
    clear_app_data(pkg)
    launch_activity(
        "com.google.android.contacts/com.android.contacts.activities.PeopleActivity"
    )
    time.sleep(3)
    _try_click_element_via_adapter("contacts", "Skip")
    time.sleep(2)
    _try_click_element_via_adapter("contacts", "Don't allow")
    time.sleep(1)
    force_stop(pkg)


def setup_dialer():
    """Dialer: just clear data."""
    clear_app_data("com.google.android.dialer")


def setup_files():
    """Files: just clear data."""
    clear_app_data("com.google.android.documentsui")


def setup_settings():
    """Settings: just clear data."""
    clear_app_data("com.android.settings")


def setup_markor():
    """Markor: click through 4 NEXT, DONE, file permission, create default folder."""
    pkg = "net.gsantner.markor"
    clear_app_data(pkg)

    # Ensure the Markor notebook directory exists before first launch.
    # AW evaluator checks files at /storage/emulated/0/Documents/Markor/.
    markor_dir = "/storage/emulated/0/Documents/Markor"
    mkdir(markor_dir)
    # Create default files so Markor recognizes the folder
    adb_shell("sh", "-c", f"echo '' > {markor_dir}/QuickNote.md")
    adb_shell("sh", "-c", f"echo '' > {markor_dir}/todo.txt")

    launch_activity(
        "net.gsantner.markor/net.gsantner.markor.activity.MainActivity"
    )
    time.sleep(3)
    for i in range(4):
        _try_click_element_via_adapter("markor", "NEXT")
        time.sleep(2)
    _try_click_element_via_adapter("markor", "DONE")
    time.sleep(2)
    _try_click_element_via_adapter("markor", "OK")
    time.sleep(2)
    _try_click_element_via_adapter("markor", "Allow access to manage all files")
    time.sleep(1)
    # Fallback: grant file management via appops
    appops_set(pkg, "android:manage_external_storage", "allow")
    force_stop(pkg)


def setup_android_world():
    """AndroidWorld app: grant overlay permission, launch and close."""
    pkg = "com.example.androidworld"
    clear_app_data(pkg)
    appops_set(pkg, "android:system_alert_window", "allow")
    launch_activity("com.example.androidworld/.MainActivity")
    time.sleep(2)
    force_stop(pkg)


def setup_clipper():
    """Clipper: install patched APK (SDK 34 compatible), launch and close."""
    pkg = "ca.zgrs.clipper"
    # Install our patched APK if not already installed.
    # The original from GCS targets SDK 0, which is rejected by API 34.
    installed = get_installed_packages()
    if pkg not in installed:
        print("  Installing patched clipper.apk (SDK 34 compatible)...")
        adb("install", "-r", "/app/docker/apks/clipper.apk")
    clear_app_data(pkg)
    launch_activity("ca.zgrs.clipper/ca.zgrs.clipper.Main")
    time.sleep(2)
    force_stop(pkg)


def setup_accessibility_forwarder():
    """Install the A11y forwarder APK and enable the accessibility service."""
    pkg = "com.google.androidenv.accessibilityforwarder"
    installed = get_installed_packages()
    if pkg not in installed:
        print("  Installing accessibility_forwarder.apk...")
        adb("install", "-r", "/app/docker/apks/accessibility_forwarder.apk")
    # Enable the accessibility service
    adb("shell", "settings", "put", "secure", "enabled_accessibility_services",
        f"{pkg}/{pkg}.AccessibilityForwarder")
    time.sleep(2)
    print("  Accessibility forwarder installed and enabled")


def setup_simple_calendar_pro():
    """Simple Calendar Pro: launch/close, grant calendar+notification perms."""
    pkg = "com.simplemobiletools.calendar.pro"
    clear_app_data(pkg)
    launch_activity(
        "com.simplemobiletools.calendar.pro/"
        "com.simplemobiletools.calendar.pro.activities.MainActivity"
    )
    time.sleep(2)
    force_stop(pkg)
    grant_permission(pkg, "android.permission.READ_CALENDAR")
    grant_permission(pkg, "android.permission.WRITE_CALENDAR")
    grant_permission(pkg, "android.permission.POST_NOTIFICATIONS")


def setup_tasks():
    """Tasks: launch and close."""
    pkg = "org.tasks"
    clear_app_data(pkg)
    launch_activity("org.tasks/com.todoroo.astrid.activity.MainActivity")
    time.sleep(2)
    force_stop(pkg)


def setup_simple_draw_pro():
    """Simple Draw Pro: just clear data."""
    clear_app_data("com.simplemobiletools.draw.pro")


def setup_simple_gallery_pro():
    """Simple Gallery Pro: grant perms, click through onboarding."""
    pkg = "com.simplemobiletools.gallery.pro"
    clear_app_data(pkg)
    for perm in [
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.ACCESS_MEDIA_LOCATION",
        "android.permission.READ_MEDIA_IMAGES",
        "android.permission.READ_MEDIA_VIDEO",
        "android.permission.POST_NOTIFICATIONS",
    ]:
        grant_permission(pkg, perm)
    launch_activity(
        "com.simplemobiletools.gallery.pro/"
        "com.simplemobiletools.gallery.pro.activities.MainActivity"
    )
    time.sleep(3)
    _try_click_element_via_adapter("simple gallery pro", "All files")
    time.sleep(2)
    _try_click_element_via_adapter(
        "simple gallery pro", "Allow access to manage all files"
    )
    time.sleep(1)
    # Fallback: grant via appops
    appops_set(pkg, "android:manage_external_storage", "allow")
    force_stop(pkg)


def setup_simple_sms_messenger():
    """Simple SMS Messenger: set as default, click through."""
    pkg = "com.simplemobiletools.smsmessenger"
    clear_app_data(pkg)
    set_default_sms_app(pkg)
    launch_activity(
        "com.simplemobiletools.smsmessenger/"
        "com.simplemobiletools.smsmessenger.activities.MainActivity"
    )
    time.sleep(3)
    _try_click_element_via_adapter("simple sms messenger", "SMS Messenger")
    time.sleep(2)
    _try_click_element_via_adapter("simple sms messenger", "Set as default")
    time.sleep(1)
    force_stop(pkg)


def setup_audio_recorder():
    """Audio Recorder: grant perms, launch via monkey."""
    pkg = "com.dimowner.audiorecorder"
    clear_app_data(pkg)
    grant_permission(pkg, "android.permission.RECORD_AUDIO")
    grant_permission(pkg, "android.permission.POST_NOTIFICATIONS")
    monkey_launch(pkg)
    time.sleep(3)
    force_stop(pkg)


def setup_miniwob():
    """MiniWoB: no special setup needed."""
    pass


def setup_pro_expense():
    """Pro Expense: click NEXT and CONTINUE."""
    pkg = "com.arduia.expense"
    clear_app_data(pkg)
    launch_activity("com.arduia.expense/com.arduia.expense.ui.MainActivity")
    time.sleep(3)
    _try_click_element_via_adapter("pro expense", "NEXT")
    time.sleep(2)
    _try_click_element_via_adapter("pro expense", "CONTINUE")
    time.sleep(2)
    force_stop(pkg)


def setup_broccoli():
    """Broccoli Recipe: launch and close."""
    pkg = "com.flauschcode.broccoli"
    clear_app_data(pkg)
    launch_activity("com.flauschcode.broccoli/com.flauschcode.broccoli.MainActivity")
    time.sleep(2)
    force_stop(pkg)


def setup_osmand():
    """OsmAnd: skip download, grant perms, copy map data."""
    pkg = "net.osmand"
    clear_app_data(pkg)
    launch_activity("net.osmand/net.osmand.plus.activities.MapActivity")
    time.sleep(3)
    _try_click_element_via_adapter("osmand", "SKIP DOWNLOAD")
    time.sleep(2)
    force_stop(pkg)
    grant_permission(pkg, "android.permission.POST_NOTIFICATIONS")

    # Copy Liechtenstein map data
    maps_device_path = "/storage/emulated/0/Android/data/net.osmand/files"
    map_file = "Liechtenstein_europe.obf"
    _copy_aw_data_to_device(map_file, maps_device_path)
    # Set security context
    adb_shell(
        "chcon", "u:object_r:media_rw_data_file:s0",
        f"{maps_device_path}/{map_file}"
    )


def setup_open_tracks():
    """Open Tracks: launch/close, grant location+notification perms."""
    pkg = "de.dennisguse.opentracks"
    launch_activity(
        "de.dennisguse.opentracks/de.dennisguse.opentracks.TrackListActivity"
    )
    time.sleep(2)
    force_stop(pkg)
    grant_permission(pkg, "android.permission.ACCESS_COARSE_LOCATION")
    grant_permission(pkg, "android.permission.ACCESS_FINE_LOCATION")
    grant_permission(pkg, "android.permission.POST_NOTIFICATIONS")
    # Bluetooth permission - try via UI
    _try_click_element_via_adapter("open tracks sports tracker", "Allow")
    time.sleep(1)
    # Also grant via adb
    try:
        grant_permission(pkg, "android.permission.BLUETOOTH_CONNECT")
    except Exception:
        pass
    launch_activity(
        "de.dennisguse.opentracks/de.dennisguse.opentracks.TrackListActivity"
    )
    time.sleep(2)
    force_stop(pkg)


def setup_vlc():
    """VLC: grant perms, create video dir, click through onboarding."""
    pkg = "org.videolan.vlc"
    clear_app_data(pkg)
    grant_permission(pkg, "android.permission.POST_NOTIFICATIONS")
    videos_path = "/storage/emulated/0/VLCVideos"
    if not check_dir_exists(videos_path):
        mkdir(videos_path)
    time.sleep(1)
    monkey_launch(pkg)
    time.sleep(3)
    _try_click_element_via_adapter("vlc", "Skip")
    time.sleep(2)
    _try_click_element_via_adapter("vlc", "GRANT PERMISSION")
    time.sleep(2)
    _try_click_element_via_adapter("vlc", "OK")
    time.sleep(2)
    _try_click_element_via_adapter("vlc", "Allow access to manage all files")
    time.sleep(1)
    # Fallback: grant via appops
    appops_set(pkg, "android:manage_external_storage", "allow")
    force_stop(pkg)


def setup_joplin():
    """Joplin: grant perms, launch to init DB, create initial note, clear."""
    pkg = "net.cozic.joplin"
    clear_app_data(pkg)
    grant_permission(pkg, "android.permission.ACCESS_COARSE_LOCATION")
    grant_permission(pkg, "android.permission.ACCESS_FINE_LOCATION")
    monkey_launch(pkg)
    time.sleep(12)  # Joplin needs extra time to initialize
    force_stop(pkg)
    time.sleep(5)

    # Create initial note via AndroidWorld's joplin_app_utils to init the DB
    try:
        _joplin_init_db()
    except Exception as e:
        print(f"  Joplin DB init warning: {e}")
        # If the AW-based approach fails, try a second launch
        monkey_launch(pkg)
        time.sleep(10)
        force_stop(pkg)


def setup_retro_music():
    """Retro Music: grant perms, launch and close."""
    pkg = "code.name.monkey.retromusic"
    clear_app_data(pkg)
    grant_permission(pkg, "android.permission.READ_MEDIA_AUDIO")
    grant_permission(pkg, "android.permission.POST_NOTIFICATIONS")
    launch_activity(
        "code.name.monkey.retromusic/.activities.MainActivity"
    )
    time.sleep(3)
    force_stop(pkg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_adapter_env = None

def _get_adapter_env():
    """Lazily create the adapter env for click_element operations."""
    global _adapter_env
    if _adapter_env is None:
        from mobile_world.runtime.controller import AndroidController
        from mobile_world.runtime.aw_env_adapter import EnvAdapter
        controller = AndroidController(device="emulator-5554")
        _adapter_env = EnvAdapter(controller)
    return _adapter_env


def _try_click_element_via_adapter(app_name: str, text: str) -> bool:
    """Try to click a UI element via the AW adapter. Returns True on success."""
    try:
        from android_world.env import tools
        env = _get_adapter_env()
        controller = tools.AndroidToolController(env=env.controller)
        controller.click_element(text)
        return True
    except Exception as e:
        print(f"  click_element('{text}') failed for {app_name}: {e}")
        return False


def _joplin_init_db():
    """Initialize Joplin's DB using AndroidWorld's joplin_app_utils."""
    from android_world.task_evals.information_retrieval import joplin_app_utils
    env = _get_adapter_env()
    joplin_app_utils.create_note(
        folder="new folder",
        title="new_note",
        body="",
        folder_mapping={},
        env=env,
    )
    joplin_app_utils.clear_dbs(env)


def _copy_aw_data_to_device(file_name: str, device_path: str):
    """Download AW data file and push to device."""
    from android_world.env.setup_device.apps import download_app_data
    local_path = download_app_data(file_name)
    adb("push", local_path, device_path + "/")


def _install_apk_via_adapter(app_class):
    """Install an app's APK using AW's download + our adapter."""
    env = _get_adapter_env()
    from android_world.env.setup_device import setup as aw_setup
    aw_setup.maybe_install_app(app_class, env)


def _save_app_snapshot(app_name: str):
    """Save per-app data snapshot using AW's snapshot system."""
    try:
        from android_world.utils import app_snapshot
        env = _get_adapter_env()
        app_snapshot.save_snapshot(app_name, env.controller)
    except Exception as e:
        print(f"  Warning: failed to save snapshot for {app_name}: {e}")


# ---------------------------------------------------------------------------
# Main setup flow
# ---------------------------------------------------------------------------

# Map app names to their setup function and AW app class
SETUP_FUNCTIONS = {
    # Pre-installed apps
    "camera": setup_camera,
    "chrome": setup_chrome,
    "clock": setup_clock,
    "contacts": setup_contacts,
    "dialer": setup_dialer,
    "files": setup_files,
    "settings": setup_settings,
    # Third-party apps
    "markor": setup_markor,
    "android world": setup_android_world,
    "clipper": setup_clipper,
    "accessibility forwarder": setup_accessibility_forwarder,
    "simple calendar pro": setup_simple_calendar_pro,
    "tasks": setup_tasks,
    "simple draw pro": setup_simple_draw_pro,
    "simple gallery pro": setup_simple_gallery_pro,
    "simple sms messenger": setup_simple_sms_messenger,
    "audio recorder": setup_audio_recorder,
    "miniwob": setup_miniwob,
    "pro expense": setup_pro_expense,
    "broccoli app": setup_broccoli,
    "osmand": setup_osmand,
    "open tracks sports tracker": setup_open_tracks,
    "vlc": setup_vlc,
    "joplin": setup_joplin,
    "retro music": setup_retro_music,
}


def main():
    from android_world.env.setup_device import apps as aw_apps

    # Map app_name -> AW AppSetup class
    aw_app_classes = {cls.app_name: cls for cls in [
        aw_apps.AndroidWorldApp, aw_apps.AudioRecorder, aw_apps.CameraApp,
        aw_apps.ChromeApp, aw_apps.ClockApp,  # ClipperApp removed — installed from patched local APK
        aw_apps.ContactsApp, aw_apps.DialerApp, aw_apps.ExpenseApp,
        aw_apps.FilesApp, aw_apps.JoplinApp, aw_apps.MarkorApp,
        aw_apps.MiniWobApp, aw_apps.OpenTracksApp, aw_apps.OsmAndApp,
        aw_apps.RecipeApp, aw_apps.RetroMusicApp, aw_apps.SettingsApp,
        aw_apps.SimpleCalendarProApp, aw_apps.SimpleDrawProApp,
        aw_apps.SimpleGalleryProApp, aw_apps.SimpleSMSMessengerApp,
        aw_apps.TasksApp, aw_apps.VlcApp,
    ]}

    # Press home to dismiss any overlays
    press_home()
    time.sleep(1)

    # Phase 1: Check what's already installed
    print("=" * 60)
    print("Phase 1: Checking installed packages")
    print("=" * 60)
    installed = get_installed_packages()
    all_expected = {**THIRD_PARTY_PACKAGES, **PREINSTALLED_PACKAGES}

    missing_pkgs = []
    for name, pkg in THIRD_PARTY_PACKAGES.items():
        if pkg in installed:
            print(f"  [OK] {name} ({pkg})")
        else:
            print(f"  [MISSING] {name} ({pkg})")
            missing_pkgs.append(name)

    # Phase 2: Install missing APKs
    if missing_pkgs:
        print()
        print("=" * 60)
        print(f"Phase 2: Installing {len(missing_pkgs)} missing APKs")
        print("=" * 60)
        install_failures = []
        for name in missing_pkgs:
            if name in aw_app_classes:
                cls = aw_app_classes[name]
                if cls.apk_names:
                    print(f"  Installing {name}...")
                    try:
                        _install_apk_via_adapter(cls)
                        print(f"  [OK] {name} installed")
                    except Exception as e:
                        print(f"  [FAIL] {name}: {e}")
                        install_failures.append(name)

        # Verify installations
        print()
        print("Verifying installations...")
        installed = get_installed_packages()
        still_missing = []
        for name, pkg in THIRD_PARTY_PACKAGES.items():
            if pkg not in installed:
                still_missing.append(name)
                print(f"  [STILL MISSING] {name} ({pkg})")
        if still_missing:
            print(f"\nWARNING: {len(still_missing)} packages failed to install!")
        else:
            print("  All third-party packages installed successfully.")
    else:
        print("\nAll third-party packages already installed.")

    # Phase 3: Run onboarding/setup for each app
    print()
    print("=" * 60)
    print("Phase 3: Running per-app setup/onboarding")
    print("=" * 60)
    setup_results = {}

    # Apps that handle their own APK installation in their setup function
    # (not installed via aw_app_classes in Phase 2)
    self_installing_apps = {"clipper", "accessibility forwarder"}

    for app_name, setup_fn in SETUP_FUNCTIONS.items():
        # Skip if the package isn't installed (for third-party apps),
        # unless the app handles its own installation.
        if app_name in THIRD_PARTY_PACKAGES and app_name not in self_installing_apps:
            pkg = THIRD_PARTY_PACKAGES[app_name]
            if pkg not in installed:
                print(f"\n[SKIP] {app_name} - package not installed")
                setup_results[app_name] = "SKIPPED"
                continue

        print(f"\n--- Setting up: {app_name} ---")
        try:
            setup_fn()
            # Save per-app data snapshot (used by AW task eval)
            _save_app_snapshot(app_name)
            print(f"  [OK] {app_name} setup complete")
            setup_results[app_name] = "OK"
        except Exception as e:
            print(f"  [FAIL] {app_name}: {e}")
            traceback.print_exc()
            setup_results[app_name] = f"FAIL: {e}"

        # Press home between apps to reset state
        press_home()
        time.sleep(1)

    # Phase 4: Summary
    print()
    print("=" * 60)
    print("Setup Summary")
    print("=" * 60)
    ok_count = sum(1 for v in setup_results.values() if v == "OK")
    fail_count = sum(1 for v in setup_results.values() if v.startswith("FAIL"))
    skip_count = sum(1 for v in setup_results.values() if v == "SKIPPED")

    for name, result in setup_results.items():
        status = "[OK]" if result == "OK" else "[FAIL]" if result.startswith("FAIL") else "[SKIP]"
        print(f"  {status} {name}")

    print()
    print(f"Total: {ok_count} OK, {fail_count} FAILED, {skip_count} SKIPPED")
    print(f"Out of {len(SETUP_FUNCTIONS)} apps")

    if fail_count > 0:
        print("\nFailed apps may need manual onboarding or have UI differences")
        print("on Pixel 8 API 34 vs AndroidWorld's expected Pixel 6 API 33.")

    # Final verification: list all installed packages
    print()
    print("=" * 60)
    print("Final Package Verification")
    print("=" * 60)
    installed = get_installed_packages()
    all_ok = True
    for name, pkg in {**THIRD_PARTY_PACKAGES, **PREINSTALLED_PACKAGES}.items():
        if pkg in installed:
            print(f"  [OK] {name}: {pkg}")
        else:
            print(f"  [MISSING] {name}: {pkg}")
            all_ok = False

    if all_ok:
        print("\nAll expected packages are installed!")
    else:
        print("\nSome packages are missing - check the output above.")


if __name__ == "__main__":
    main()
