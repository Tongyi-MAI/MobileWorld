"""Redroid container /data reset — the redroid analog of a QEMU snapshot load.

On the emulator, per-task isolation comes from ``adb emu avd snapshot load init_state``,
which restores the whole device (the apps' local ``/data`` included) so the device
frontend stays in lockstep with the backend reset done by ``start_*_backend``. redroid
has no QEMU snapshots, so this module reimplements "snapshot load" as a restore of the
whole golden ``/data`` volume: stop the container, replace the volume contents with the
golden baseline, restart, and wait for Android to finish booting.

Without this, only the backend resets to golden each task while the phone keeps its
drifted local state (cached posts, sync cursors, read markers, sessions) — the frontend
slowly diverges from the freshly-seeded backend. Restoring the data *directory* (not
``pm clear``) also preserves the golden app auth token, which matches the golden
``sessions`` row the backend reset restores, so apps come back logged-in and consistent.

Everything is env-driven so the emulator path is untouched and a redroid host without a
captured baseline degrades to the previous no-op:

- ``REDROID_CONTAINER``      container name to restart (default ``redroid14-sandbox``)
- ``REDROID_DATA_VOLUME``    docker volume backing ``/data`` (default ``redroid14-gms-data``)
- ``REDROID_DATA_BASELINE``  path to the golden ``/data`` tarball (default ``/root/redroid-data.tgz``)
- ``REDROID_BOOT_TIMEOUT``   seconds to wait for ``sys.boot_completed`` (default ``180``)
"""

import base64
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import time

from loguru import logger


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _run(cmd: list[str], timeout: int | None = None, check: bool = False):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)


def _real_now_epoch() -> int:
    """Real host epoch, even when this process is itself clock-shifted.

    The MW server is LD_PRELOAD'd with the timeshift glibc shim, so datetime.now() here
    returns the shifted frame. Spawn `date +%s` with LD_PRELOAD stripped to read the
    true host CLOCK_REALTIME for offset math.
    """
    env = {k: v for k, v in os.environ.items() if k not in ("LD_PRELOAD", "TIMESHIFT_OFFSET_FILE")}
    r = subprocess.run(["date", "+%s"], capture_output=True, text=True, env=env, timeout=10)
    return int(r.stdout.strip())


def _sql_str(value: str) -> str:
    """Quote a Python string as a SQLite string literal (doubling single quotes).

    Robust for arbitrary content — Chinese OTP text, embedded quotes, newlines —
    because the SQL is fed to ``sqlite3`` over stdin (never re-parsed by a shell).
    """
    return "'" + str(value).replace("'", "''") + "'"


def _device_sqlite(serial: str, db_path: str, sql: str, timeout: int = 30):
    """Run SQL against an on-device sqlite DB as root, feeding SQL via stdin.

    Piping the SQL through stdin to ``adb shell sqlite3 <db>`` (a command-form adb
    shell, so no PTY is allocated) avoids any device-side shell re-tokenizing of the
    statement — the bug that silently broke the old ``content insert`` path for any
    multi-word SMS body. When guest timeshift is active, preload the same shim used by
    zygote so SQLite ``strftime('now')`` triggers see the task frame instead of the
    shared redroid host clock.
    """
    cmd = ["adb", "-s", serial, "shell"]
    if _env("REDROID_TIMESHIFT", "1") == "1":
        guest_timeshift_so = _env("REDROID_GUEST_TIMESHIFT_SO", "/system/lib64/libtimeshift.so")
        cmd.extend(["env", f"LD_PRELOAD={guest_timeshift_so}"])
    cmd.extend(["sqlite3", db_path])
    return subprocess.run(
        cmd,
        input=sql,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _volume_mountpoint(volume: str) -> str | None:
    r = _run(["docker", "volume", "inspect", volume, "--format", "{{.Mountpoint}}"])
    return r.stdout.strip() or None


def _safe_data_mountpoint(volume: str) -> str | None:
    """Resolve the volume's host mountpoint, guarding against a wipe of the wrong path.

    A docker named-volume mountpoint is always ``.../volumes/<name>/_data``; refuse
    anything that doesn't match so a bad ``docker volume inspect`` (e.g. ``/`` or empty)
    can never feed a recursive delete.
    """
    mp = _volume_mountpoint(volume)
    if not mp or "/volumes/" not in mp or not mp.rstrip("/").endswith("_data"):
        logger.error(f"[redroid] refusing unsafe mountpoint for volume {volume!r}: {mp!r}")
        return None
    if not os.path.isdir(mp):
        logger.error(f"[redroid] mountpoint {mp!r} for volume {volume!r} is not a directory")
        return None
    return mp


_ADB_RELAY_SOCKET = "/run/redroid-adbd.sock"
_ADB_RELAY_PID_FILE = "/run/redroid-adb-unix-relay.pid"


def _stop_stale_adb_unix_relays() -> None:
    """Stop socat instances pinned to an obsolete Redroid network namespace."""
    targets: set[int] = set()
    try:
        with open(_ADB_RELAY_PID_FILE) as f:
            targets.add(int(f.read().strip()))
    except (FileNotFoundError, ValueError, OSError):
        pass

    # The first image built before pidfile support may still be running. Locate
    # only the exact Unix-listener relay; never kill the outer :5555/:5556 relays.
    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            try:
                cmdline = open(f"/proc/{entry.name}/cmdline", "rb").read().replace(b"\0", b" ")
            except OSError:
                continue
            if b"socat" in cmdline and b"UNIX-LISTEN:/run/redroid-adbd.sock" in cmdline:
                targets.add(int(entry.name))
    except OSError:
        pass

    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        os.unlink(_ADB_RELAY_SOCKET)
    except FileNotFoundError:
        pass


def _refresh_adb_relay(container: str, timeout: float = 5.0) -> bool:
    """Bind outer localhost:5555 to adbd in the container's current netns.

    ``docker stop/start`` gives Redroid a new network namespace. The outer TCP
    socat listener remains valid, but its Unix-socket peer must be recreated in
    that new namespace before adb can rediscover ``emulator-5554``.
    """
    _stop_stale_adb_unix_relays()
    inspected = _run(["docker", "inspect", "-f", "{{.State.Pid}}", container], timeout=30)
    try:
        redroid_pid = int(inspected.stdout.strip())
    except ValueError:
        redroid_pid = 0
    if inspected.returncode != 0 or redroid_pid <= 0:
        logger.error(
            f"[redroid] cannot refresh ADB relay: invalid container pid "
            f"{inspected.stdout.strip()!r} ({inspected.stderr.strip()})"
        )
        return False

    relay = subprocess.Popen(
        [
            "nsenter",
            "-t",
            str(redroid_pid),
            "-n",
            "socat",
            f"UNIX-LISTEN:{_ADB_RELAY_SOCKET},fork,unlink-early,mode=0666",
            "TCP6:[::1]:5555",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with open(_ADB_RELAY_PID_FILE, "w") as f:
        f.write(str(relay.pid))

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if stat.S_ISSOCK(os.stat(_ADB_RELAY_SOCKET).st_mode):
                _run(["adb", "reconnect", "offline"], timeout=15)
                logger.info(
                    f"[redroid] refreshed ADB relay for container pid {redroid_pid} "
                    f"(relay pid {relay.pid})"
                )
                return True
        except FileNotFoundError:
            pass
        if relay.poll() is not None:
            break
        time.sleep(0.1)

    logger.error(f"[redroid] ADB relay failed to create {_ADB_RELAY_SOCKET}")
    return False


def _start_redroid_container(container: str) -> bool:
    started = _run(["docker", "start", container], timeout=120)
    if started.returncode != 0:
        logger.error(f"[redroid] failed to start {container}: {started.stderr.strip()}")
        return False
    return _refresh_adb_relay(container)


def _wait_redroid_stable(
    container: str,
    serial: str,
    timeout: int,
    stable_seconds: float | None = None,
) -> bool:
    """Wait for boot_completed on a stable Redroid container PID.

    The first start after restoring ``/data`` can exit 129 roughly 25 seconds
    after reporting boot_completed. Docker's restart policy recovers it, but the
    ADB relay is then pinned to the dead network namespace. Track PID changes,
    rebind the relay, and require a stable window before returning to task code.
    """
    if stable_seconds is None:
        stable_seconds = float(_env("REDROID_STABLE_SECONDS", "35"))
    deadline = time.monotonic() + timeout
    last_pid = 0
    boot_stable_since: float | None = None

    while time.monotonic() < deadline:
        inspected = _run(
            ["docker", "inspect", "-f", "{{.State.Pid}} {{.State.Running}}", container],
            timeout=30,
        )
        fields = inspected.stdout.split()
        try:
            current_pid = int(fields[0]) if fields and fields[-1] == "true" else 0
        except ValueError:
            current_pid = 0

        if current_pid > 0 and current_pid != last_pid:
            logger.info(
                f"[redroid] container pid changed {last_pid or 'none'} -> {current_pid}; "
                "rebinding ADB relay"
            )
            if not _refresh_adb_relay(container):
                time.sleep(2)
                continue
            last_pid = current_pid
            boot_stable_since = None

        if current_pid <= 0:
            boot_stable_since = None
            time.sleep(2)
            continue

        if ":" in serial:
            _run(["adb", "connect", serial], timeout=15)
        boot = _run(["adb", "-s", serial, "shell", "getprop", "sys.boot_completed"], timeout=15)
        if boot.stdout.strip() == "1":
            if boot_stable_since is None:
                boot_stable_since = time.monotonic()
            if time.monotonic() - boot_stable_since >= stable_seconds:
                logger.info(
                    f"[redroid] pid {current_pid} booted and stable for {stable_seconds:.0f}s"
                )
                return True
        else:
            boot_stable_since = None
        time.sleep(2)

    logger.error(f"[redroid] {container}/{serial} did not reach a stable boot within {timeout}s")
    return False


def _wait_boot_completed(serial: str, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ":" in serial:
            _run(["adb", "connect", serial], timeout=15)
        r = _run(["adb", "-s", serial, "shell", "getprop", "sys.boot_completed"], timeout=15)
        if r.stdout.strip() == "1":
            return True
        time.sleep(3)
    return False


_GUEST_TS_FILE = "/data/local/tmp/timeshift_offset"


def _write_guest_offset_file(serial: str, offset) -> None:
    """Sync libtimeshift's file fallback with the property (some guest procs read the file)."""
    _run(
        [
            "adb",
            "-s",
            serial,
            "shell",
            f"su 0 sh -c \"printf '%s' '{offset}' > {_GUEST_TS_FILE} && chmod 644 {_GUEST_TS_FILE}\"",
        ],
        timeout=15,
    )


def reapply_timeshift(serial: str) -> None:
    """Re-apply the per-container guest time offset after a ``/data`` restore.

    libtimeshift's .so + the zygote LD_PRELOAD live in ``/system`` and survive the
    docker stop/start, but the offset property lives in ``/data``, which this restore
    wipes back to the golden baseline (no offset). Without re-applying, the shim reads
    0 and the guest reverts to real host time after the first task. The offset (seconds,
    guest_wallclock - host_realtime) comes from the entrypoint via ``TIMESHIFT_OFFSET_FILE``.
    """
    if _env("REDROID_TIMESHIFT", "1") != "1":
        return
    off_file = _env("TIMESHIFT_OFFSET_FILE", "/run/timeshift_offset")
    try:
        offset = open(off_file).read().strip()
        int(offset)
    except Exception as e:
        logger.warning(f"[redroid] timeshift offset unavailable ({off_file!r}): {e}")
        return
    _run(
        ["adb", "-s", serial, "shell", "su", "0", "setprop", "persist.sys.timeshift_off", offset],
        timeout=15,
    )
    _write_guest_offset_file(serial, offset)
    logger.info(f"[redroid] re-applied timeshift offset {offset}s after /data restore")


def set_task_timeframe(serial: str, date_str: str, realtime: bool = False) -> bool:
    """Set the libtimeshift offset for guest and verifier.

    realtime=True: offset 0 (wall clock). Otherwise: pin to <date_str> 12:00 UTC.
    No-op unless REDROID_TIMESHIFT is enabled.
    """
    if _env("REDROID_TIMESHIFT", "1") != "1":
        return True
    try:
        if realtime:
            offset = 0
        else:
            import datetime

            dt = datetime.datetime.strptime(
                date_str.strip()[:10] + " 12:00:00", "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=datetime.UTC)
            offset = int(dt.timestamp()) - _real_now_epoch()
        off_file = _env("TIMESHIFT_OFFSET_FILE", "/run/timeshift_offset")
        with open(off_file, "w") as f:
            f.write(str(offset))
        _run(
            [
                "adb",
                "-s",
                serial,
                "shell",
                "su",
                "0",
                "setprop",
                "persist.sys.timeshift_off",
                str(offset),
            ],
            timeout=15,
        )
        _write_guest_offset_file(serial, offset)
        time.sleep(1.2)
        _run(
            [
                "adb",
                "-s",
                serial,
                "shell",
                "am",
                "broadcast",
                "-a",
                "android.intent.action.TIME_SET",
            ],
            timeout=15,
        )
        if not _wait_system_services_ready(serial, timeout=90):
            logger.error("[redroid] Android framework did not stabilize after time-frame change")
            return False
        logger.info(
            f"[redroid] task time frame = {'realtime' if realtime else date_str} (offset {offset}s)"
        )
        return True
    except Exception as e:
        logger.error(f"[redroid] set_task_timeframe failed: {e}")
        return False


def _wait_system_services_ready(serial: str, timeout: int = 60, stable_seconds: float = 5) -> bool:
    need = ("package", "activity", "input", "window")
    deadline = time.monotonic() + timeout
    ready_since: float | None = None
    while time.monotonic() < deadline:
        if ":" in serial:
            _run(["adb", "connect", serial], timeout=15)
        services_ready = all(
            "found"
            in (
                _run(["adb", "-s", serial, "shell", "service", "check", s], timeout=15).stdout or ""
            )
            for s in need
        )
        viewport = _run(["adb", "-s", serial, "shell", "wm", "size"], timeout=15)
        if services_ready and "Physical size:" in (viewport.stdout or ""):
            if ready_since is None:
                ready_since = time.monotonic()
            if time.monotonic() - ready_since >= stable_seconds:
                return True
        else:
            ready_since = None
        time.sleep(2)
    return False


def wait_for_sdcard_ready(serial: str, timeout: int = 120) -> bool:
    deadline = time.monotonic() + timeout
    probe = "/sdcard/.mw_storage_probe"
    while time.monotonic() < deadline:
        if ":" in serial:
            _run(["adb", "connect", serial], timeout=15)
        r = _run(
            ["adb", "-s", serial, "shell", f"touch {probe} && rm -f {probe} && echo READY"],
            timeout=15,
        )
        if "READY" in (r.stdout or ""):
            return True
        time.sleep(2)
    return False


def restart_zygote(serial: str) -> bool:
    if _env("REDROID_TIMESHIFT", "1") != "1":
        return True
    try:
        _run(
            ["adb", "-s", serial, "shell", "su", "0", "setprop", "ctl.restart", "zygote"],
            timeout=15,
        )
        time.sleep(4)
        ready = _wait_system_services_ready(serial)
        sdcard_ready = wait_for_sdcard_ready(serial)
        logger.info(
            f"[redroid] restarted zygote to re-cache timeshift offset; "
            f"services_ready={ready} sdcard_ready={sdcard_ready}"
        )
        return ready and sdcard_ready
    except Exception as e:
        logger.warning(f"[redroid] restart_zygote failed: {e}")
        return False


def restore_golden_data(serial: str) -> bool:
    """Restore the golden ``/data`` baseline into the redroid container and reboot it.

    Returns True on success. When no baseline file is configured/present, logs a warning
    and returns True (a safe no-op, matching the old behaviour) so hosts without a
    captured baseline are unaffected.
    """
    container = _env("REDROID_CONTAINER", "redroid14-sandbox")
    volume = _env("REDROID_DATA_VOLUME", "redroid14-gms-data")
    baseline = _env("REDROID_DATA_BASELINE", "/root/redroid-data.tgz")
    boot_timeout = int(_env("REDROID_BOOT_TIMEOUT", "180"))

    if not os.path.exists(baseline):
        logger.warning(
            f"[redroid] golden /data baseline {baseline} not found; skipping /data restore "
            "(snapshot-load is a no-op on this host)."
        )
        return True

    mountpoint = _safe_data_mountpoint(volume)
    if not mountpoint:
        return False

    logger.info(
        f"[redroid] snapshot-load -> restoring golden /data from {baseline} into {mountpoint}"
    )
    try:
        # 1. stop the container
        _run(["docker", "stop", "-t", "1", container], timeout=120, check=True)

        # 2. restore the volume to the golden baseline
        golden_dir = _env("REDROID_DATA_GOLDEN_DIR", "")
        if golden_dir and os.path.isdir(golden_dir) and os.listdir(golden_dir):
            r = _run(["rsync", "-a", "--delete", f"{golden_dir}/", f"{mountpoint}/"], timeout=600)
            if r.returncode != 0:
                logger.error(
                    f"[redroid] rsync restore from {golden_dir} failed: {r.stderr.strip()}"
                )
                _start_redroid_container(container)
                return False
        else:
            wipe = _run(["find", mountpoint, "-mindepth", "1", "-delete"], timeout=300)
            if wipe.returncode != 0:
                logger.error(f"[redroid] failed to wipe {mountpoint}: {wipe.stderr.strip()}")
                _start_redroid_container(container)
                return False
            untar = _run(["tar", "xf", baseline, "-C", mountpoint], timeout=600)
            if untar.returncode != 0:
                logger.error(
                    f"[redroid] failed to restore baseline into {mountpoint}: {untar.stderr.strip()}"
                )
                _start_redroid_container(container)
                return False

        # 3. start the container and wait for Android to finish booting
        if not _start_redroid_container(container):
            return False
        if not _wait_redroid_stable(container, serial, boot_timeout):
            logger.error(
                f"[redroid] device {serial} did not reach a stable boot in {boot_timeout}s"
            )
            return False

        _run(["adb", "-s", serial, "root"], timeout=30)
        time.sleep(2)
        if ":" in serial:
            _run(["adb", "connect", serial], timeout=15)

        _wait_system_services_ready(serial)
        wait_for_sdcard_ready(serial)

        reapply_timeshift(serial)
        reseed_golden_sms(serial)

        # POST_NOTIFICATIONS is a runtime permission stored in /data/system
        _run(
            [
                "adb",
                "-s",
                serial,
                "shell",
                "pm",
                "grant",
                "com.mobileworld.smsnotifier",
                "android.permission.POST_NOTIFICATIONS",
            ],
            timeout=15,
        )

        reseed_contact_nicknames(serial)
        reseed_launcher_shortcuts(serial)
        patch_vold_appfuse(serial)

        # The post-boot root/vold operations can briefly recycle adbd. Rebind to
        # the current container PID and require one final healthy interval before
        # task initialization sends its first HOME/APP_SWITCH events.
        # The delayed exit-129 can land just after the post-root/vold operations.
        # Five seconds was one second too short on the ARM Colima host, allowing
        # task initialization to continue with an ADB relay pinned to the dead PID.
        if not _wait_redroid_stable(container, serial, 90, stable_seconds=15):
            return False
        if not _wait_system_services_ready(serial, timeout=90):
            return False

        logger.info("[redroid] golden /data restored, device rebooted, adb root re-asserted")
        return True
    except subprocess.TimeoutExpired as e:
        logger.error(f"[redroid] timeout during /data restore: {e}")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(
            f"[redroid] command failed during /data restore: {e} :: {(e.stderr or '').strip()}"
        )
        return False
    except Exception as e:
        logger.error(f"[redroid] unexpected error during /data restore: {e}")
        return False


# --- Contact nickname reseed --------------------------------------------------
_CONTACT_NICKNAME_SEEDS = [("Robert Pattinson", "rainbow123")]
_CONTACTS_DATA_URI = "content://com.android.contacts/data"
_NICKNAME_MIME = "vnd.android.cursor.item/nickname"


def _contacts_query(serial: str, uri: str, projection: str):
    return (
        _run(
            [
                "adb",
                "-s",
                serial,
                "shell",
                "content",
                "query",
                "--uri",
                uri,
                "--projection",
                projection,
            ],
            timeout=25,
        ).stdout
        or ""
    )


def _contact_raw_id(serial: str, display_name: str) -> str | None:
    out = _contacts_query(serial, "content://com.android.contacts/raw_contacts", "_id:display_name")
    for line in out.splitlines():
        if f"display_name={display_name}" in line:
            m = re.search(r"_id=(\d+)", line)
            if m:
                return m.group(1)
    return None


def reseed_contact_nicknames(serial: str) -> None:
    """Idempotently re-apply golden contact nicknames via the contacts provider."""
    data = _contacts_query(serial, _CONTACTS_DATA_URI, "display_name:mimetype:data1")
    for display_name, nickname in _CONTACT_NICKNAME_SEEDS:
        try:
            if any(
                f"display_name={display_name}" in ln
                and "item/nickname" in ln
                and f"data1={nickname}" in ln
                for ln in data.splitlines()
            ):
                continue  # already present
            rid = _contact_raw_id(serial, display_name)
            if not rid:
                logger.warning(f"[redroid] nickname reseed: contact {display_name!r} not found")
                continue
            _run(
                [
                    "adb",
                    "-s",
                    serial,
                    "shell",
                    "content",
                    "insert",
                    "--uri",
                    _CONTACTS_DATA_URI,
                    "--bind",
                    f"raw_contact_id:i:{rid}",
                    "--bind",
                    f"mimetype:s:{_NICKNAME_MIME}",
                    "--bind",
                    f"data1:s:{nickname}",
                ],
                timeout=20,
            )
            logger.info(f"[redroid] reseeded nickname for {display_name!r}: {nickname}")
        except Exception as e:
            logger.warning(f"[redroid] nickname reseed failed for {display_name!r}: {e}")


# --- Launcher3 home-screen shortcuts -----------------------------------------
_LAUNCHER_PACKAGE = "com.android.launcher3"
_LAUNCHER_DB_DIR = f"/data/data/{_LAUNCHER_PACKAGE}/databases"
_LAUNCHER_DB_NAMES = ("launcher.db", "launcher_6_by_5.db")
_LAUNCHER_SHORTCUTS = (
    (
        "Taodian",
        "com.testmall.app/io.dcloud.PandoraEntry",
        2,
        2,
    ),
    (
        "Firefox",
        "org.mozilla.firefox/.App",
        3,
        2,
    ),
)


def _launcher_shortcut_sql() -> str:
    statements = ["PRAGMA busy_timeout=5000;", "BEGIN IMMEDIATE;"]
    for title, component, cell_x, cell_y in _LAUNCHER_SHORTCUTS:
        intent = (
            "#Intent;action=android.intent.action.MAIN;"
            "category=android.intent.category.LAUNCHER;"
            "launchFlags=0x10200000;"
            f"component={component};end"
        )
        statements.append(
            """
            INSERT INTO favorites (
                _id, title, intent, container, screen, cellX, cellY,
                spanX, spanY, itemType, appWidgetId, modified, restored,
                profileId, rank, options, appWidgetSource
            )
            SELECT
                (SELECT COALESCE(MAX(_id), 0) + 1 FROM favorites),
                {title}, {intent}, -100, 0, {cell_x}, {cell_y},
                1, 1, 0, -1, 0, 0, 0, 0, 0, -1
            WHERE NOT EXISTS (
                SELECT 1 FROM favorites
                WHERE itemType = 0 AND intent LIKE {component_match}
            )
            AND NOT EXISTS (
                SELECT 1 FROM favorites
                WHERE container = -100 AND screen = 0
                  AND cellX = {cell_x} AND cellY = {cell_y}
            );
            """.format(
                title=_sql_str(title),
                intent=_sql_str(intent),
                component_match=_sql_str(f"%component={component};%"),
                cell_x=cell_x,
                cell_y=cell_y,
            )
        )
    statements.append("COMMIT;")
    return "\n".join(statements)


def reseed_launcher_shortcuts(serial: str) -> bool:
    """Idempotently pin Taodian and Firefox to the Launcher3 home screen.

    The ARM golden ``/data`` snapshot predates these two workspace entries even
    though both APKs are installed. Apply the small Launcher3 DB migration on
    initial container boot and after every golden-data restore so the visible
    workspace remains aligned with the emulator baseline.
    """
    try:
        _run(
            ["adb", "-s", serial, "shell", "am", "force-stop", _LAUNCHER_PACKAGE],
            timeout=15,
        )
        seeded_dbs: list[str] = []
        for db_name in _LAUNCHER_DB_NAMES:
            db_path = f"{_LAUNCHER_DB_DIR}/{db_name}"
            exists = _run(
                ["adb", "-s", serial, "shell", "test", "-f", db_path],
                timeout=10,
            )
            if exists.returncode != 0:
                continue
            result = _device_sqlite(serial, db_path, _launcher_shortcut_sql())
            if result.returncode != 0:
                logger.warning(
                    f"[redroid] Launcher3 shortcut reseed failed for {db_name}: "
                    f"{result.stderr.strip()}"
                )
                continue
            seeded_dbs.append(db_name)

        if not seeded_dbs:
            logger.warning("[redroid] Launcher3 shortcut reseed found no writable database")
            return False

        # A root sqlite client may briefly create journal/WAL sidecars. Restore
        # ownership/context before Launcher3 opens the databases again.
        _run(
            [
                "adb",
                "-s",
                serial,
                "shell",
                "su",
                "0",
                "sh",
                "-c",
                f"owner=$(stat -c '%u:%g' {_LAUNCHER_DB_DIR}/launcher.db); "
                f"chown $owner {_LAUNCHER_DB_DIR}/launcher*.db* 2>/dev/null || true; "
                f"restorecon -RF {_LAUNCHER_DB_DIR} 2>/dev/null || true",
            ],
            timeout=20,
        )
        _run(
            [
                "adb",
                "-s",
                serial,
                "shell",
                "am",
                "start",
                "-W",
                "-a",
                "android.intent.action.MAIN",
                "-c",
                "android.intent.category.HOME",
            ],
            timeout=30,
        )
        logger.info(
            "[redroid] Launcher3 home-screen shortcuts ready: "
            f"Taodian + Firefox ({', '.join(seeded_dbs)})"
        )
        return True
    except Exception as e:
        logger.warning(f"[redroid] Launcher3 shortcut reseed failed: {e}")
        return False


# --- vold AppFuse patch -------------------------------------------------------
_VOLD_PATH = "/system/bin/vold"
_VOLD_APPFUSE_NEEDLE = b'group_id=0,context="u:object_r:app_fuse_file:s0"'


def _vold_appfuse_patched(serial: str) -> bool | None:
    r = _run(
        ["adb", "-s", serial, "shell", f"strings {_VOLD_PATH} | grep -c 'group_id=0,context='"],
        timeout=30,
    )
    if r.returncode not in (0, 1):
        return None
    out = (r.stdout or "").strip()
    return int(out) == 0 if out.isdigit() else None


def patch_vold_appfuse(serial: str) -> bool:
    already = _vold_appfuse_patched(serial)
    if already is True:
        return True
    if already is None:
        logger.warning("[redroid] vold appfuse: could not read vold; skipping patch")
        return False
    try:
        import tempfile

        _run(["adb", "-s", serial, "shell", "mount", "-o", "rw,remount", "/"], timeout=15)
        with tempfile.TemporaryDirectory() as td:
            local = os.path.join(td, "vold")
            if _run(["adb", "-s", serial, "pull", _VOLD_PATH, local], timeout=60).returncode != 0:
                logger.warning("[redroid] vold appfuse: pull failed; skipping patch")
                return False
            with open(local, "rb") as fh:
                data = bytearray(fh.read())
            i = data.find(_VOLD_APPFUSE_NEEDLE)
            if i < 0:
                logger.warning("[redroid] vold appfuse: option string not found; skipping patch")
                return False
            comma = i + len(b"group_id=0")
            if data[comma] != 0x2C:
                logger.warning("[redroid] vold appfuse: unexpected byte at patch offset; skipping")
                return False
            data[comma] = 0x00
            with open(local, "wb") as fh:
                fh.write(data)
            staged = "/system/bin/.vold.affix.new"
            if _run(["adb", "-s", serial, "push", local, staged], timeout=60).returncode != 0:
                logger.warning("[redroid] vold appfuse: push failed; skipping patch")
                return False
        _run(["adb", "-s", serial, "shell", "chmod", "0755", staged], timeout=15)
        _run(["adb", "-s", serial, "shell", "chown", "0:2000", staged], timeout=15)
        _run(
            [
                "adb",
                "-s",
                serial,
                "shell",
                f"[ -f {_VOLD_PATH}.affix.orig ] || cp -a {_VOLD_PATH} {_VOLD_PATH}.affix.orig",
            ],
            timeout=20,
        )
        if (
            _run(["adb", "-s", serial, "shell", "mv", staged, _VOLD_PATH], timeout=15).returncode
            != 0
        ):
            logger.warning("[redroid] vold appfuse: mv over vold failed; skipping patch")
            return False
        _run(["adb", "-s", serial, "shell", "kill $(pidof vold)"], timeout=15)
        for _ in range(10):
            time.sleep(1)
            if (
                _run(["adb", "-s", serial, "shell", "getprop", "init.svc.vold"], timeout=10).stdout
                or ""
            ).strip() == "running":
                break

        ok = _vold_appfuse_patched(serial) is True
        logger.info(f"[redroid] vold appfuse patched (context= stripped, vold restarted); ok={ok}")
        return ok
    except Exception as e:
        logger.warning(f"[redroid] vold appfuse patch failed: {e}")
        return False


# --- Mattermost guest-app sync ------------------------------------------------
_MM_APP_PKG = "com.mattermost.rnbeta"
_MM_GUEST_SERVER_URL = "http://10.0.2.2:8065"


def _mm_app_db_path() -> str:
    name = base64.b64encode(_MM_GUEST_SERVER_URL.encode()).decode()
    return f"/data/data/{_MM_APP_PKG}/files/databases/{name}.db"


def _mm_my_channel_count(serial: str) -> int:
    r = _device_sqlite(serial, _mm_app_db_path(), "SELECT count(*) FROM MyChannel;", timeout=20)
    try:
        return int((r.stdout or "").strip())
    except ValueError:
        return -1


def sync_mattermost_app(serial: str, timeout: int = 90) -> bool:
    db = _mm_app_db_path()
    if _run(["adb", "-s", serial, "shell", "test", "-f", db]).returncode != 0:
        logger.warning("[redroid] mattermost app DB not found; skipping app sync")
        return False

    _run(["adb", "-s", serial, "shell", "am", "force-stop", _MM_APP_PKG], timeout=30)
    _run(["adb", "-s", serial, "logcat", "-c"], timeout=15)
    _run(
        ["adb", "-s", serial, "shell", "am", "start", "-n", f"{_MM_APP_PKG}/.MainActivity"],
        timeout=30,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(3)
        out = _run(["adb", "-s", serial, "logcat", "-d"], timeout=20).stdout or ""
        if "WEBSOCKET RECONNECT MODELS BATCHING" in out:
            time.sleep(3)
            logger.info(
                f"[redroid] mattermost app synced (MyChannel={_mm_my_channel_count(serial)})"
            )
            return True
    logger.warning("[redroid] mattermost app reconnect-sync not observed within timeout")
    return False


def set_host_clock(date_str: str, realtime: bool = False) -> bool:
    if _env("REDROID_SET_HOST_CLOCK", "1").strip().lower() not in ("1", "true", "yes", "on"):
        return True
    try:
        if realtime:
            r = _run(["timedatectl", "set-ntp", "true"], timeout=30)
            logger.info("[redroid] re-enabled NTP (real-time frame for time-sync task)")
            return r.returncode == 0
        ts = f"{date_str} 12:00:00"
        _run(["timedatectl", "set-ntp", "false"], timeout=30)
        r = _run(["date", "-u", "-s", ts], timeout=30)
        if r.returncode != 0:
            r = _run(["timedatectl", "set-time", ts], timeout=30)
        if r.returncode != 0:
            logger.error(f"[redroid] failed to set host clock to {ts} UTC: {r.stderr.strip()}")
            return False
        logger.info(f"[redroid] host clock pinned to {ts} UTC (benchmark reference frame)")
        return True
    except Exception as e:
        logger.error(f"[redroid] set_host_clock failed: {e}")
        return False


# --- simulated inbound SMS -------------------------------------------------
_SMS_PROVIDER_DB = _env(
    "REDROID_SMS_PROVIDER_DB",
    "/data/user_de/0/com.android.providers.telephony/databases/mmssms.db",
)
_SMS_FOSSIFY_PKG = _env("REDROID_SMS_FOSSIFY_PKG", "org.fossify.messages")
_SMS_FOSSIFY_DB = _env(
    "REDROID_SMS_FOSSIFY_DB",
    "/data/data/org.fossify.messages/databases/conversations.db",
)
_GOLDEN_SMS_PROVIDER_SQL = _env(
    "REDROID_GOLDEN_SMS_SQL", "/root/redroid_assets/golden/provider_sms_golden.sql"
)
_GOLDEN_FOSSIFY_DB = _env(
    "REDROID_GOLDEN_FOSSIFY_DB", "/root/redroid_assets/golden/conversations_golden.db"
)


def _resolve_thread_id(serial: str, sender: str) -> int | None:
    r = _run(
        [
            "adb",
            "-s",
            serial,
            "shell",
            "content",
            "query",
            "--uri",
            f"content://mms-sms/threadID?recipient={sender}",
        ],
        timeout=30,
    )
    m = re.search(r"_id=(\d+)", (r.stdout or "") + (r.stderr or ""))
    return int(m.group(1)) if m else None


def inject_inbound_sms(serial: str, sender: str, message: str) -> tuple[bool, str]:
    tid = _resolve_thread_id(serial, sender)
    if tid is None:
        return False, "could not resolve/create telephony thread_id for sender"

    ts_ms = int(time.time() * 1000)
    ts_s = ts_ms // 1000

    prov_sql = (
        "INSERT INTO sms (thread_id,address,date,date_sent,read,type,body,seen,sub_id) "
        f"VALUES ({tid},{_sql_str(sender)},{ts_ms},{ts_ms},0,1,{_sql_str(message)},0,-1);\n"
        "SELECT last_insert_rowid();\n"
    )
    r = _device_sqlite(serial, _SMS_PROVIDER_DB, prov_sql)
    ids = re.findall(r"\d+", r.stdout or "")
    if r.returncode != 0 or not ids:
        return False, f"provider write failed: {(r.stderr or r.stdout).strip()[:200]}"
    sms_id = int(ids[-1])

    have_fossify = (
        _run(["adb", "-s", serial, "shell", "test", "-f", _SMS_FOSSIFY_DB]).returncode == 0
    )
    if not have_fossify:
        logger.warning(
            f"[redroid] {_SMS_FOSSIFY_DB} missing; SMS landed in the provider only "
            "(it may not show in the Messages UI)."
        )
        return True, f"provider-only (thread {tid}, sms _id {sms_id})"

    participants = json.dumps(
        [
            {
                "anniversaries": [],
                "birthdays": [],
                "contactId": 0,
                "name": sender,
                "phoneNumbers": [
                    {
                        "isPrimary": False,
                        "label": "",
                        "normalizedNumber": sender,
                        "type": 0,
                        "value": sender,
                    }
                ],
                "photoUri": "",
                "rawId": 0,
            }
        ],
        ensure_ascii=False,
    )
    foss_sql = (
        "INSERT OR REPLACE INTO messages "
        "(id,body,type,status,participants,date,read,thread_id,is_mms,attachment,"
        "sender_phone_number,sender_name,sender_photo_uri,subscription_id,is_scheduled) "
        f"VALUES ({sms_id},{_sql_str(message)},1,-1,{_sql_str(participants)},{ts_s},0,"
        f"{tid},0,'null',{_sql_str(sender)},{_sql_str(sender)},'',-1,0);\n"
        "INSERT INTO conversations "
        "(thread_id,snippet,date,read,title,photo_uri,is_group_conversation,phone_number,"
        "is_scheduled,uses_custom_title,archived,unread_count) "
        f"VALUES ({tid},{_sql_str(message)},{ts_s},0,{_sql_str(sender)},'',0,"
        f"{_sql_str(sender)},0,0,0,1) "
        f"ON CONFLICT(thread_id) DO UPDATE SET snippet={_sql_str(message)},date={ts_s},"
        "read=0,unread_count=unread_count+1;\n"
    )
    r = _device_sqlite(serial, _SMS_FOSSIFY_DB, foss_sql)
    if r.returncode != 0:
        return False, f"fossify cache write failed: {(r.stderr or r.stdout).strip()[:200]}"

    try:
        dev_cmd = (
            "am broadcast -f 32 -a com.mobileworld.smsnotifier.SHOW "
            "-n com.mobileworld.smsnotifier/.NotifyReceiver "
            f"--es sender {shlex.quote(sender)} --es body {shlex.quote(message)}"
        )
        _run(["adb", "-s", serial, "shell", dev_cmd], timeout=15)
    except Exception as e:
        logger.warning(f"[redroid] SMS notification broadcast failed (non-fatal): {e}")

    logger.info(f"[redroid] injected inbound SMS from {sender!r} (thread {tid}, sms _id {sms_id})")
    return True, f"thread {tid}, sms _id {sms_id}"


def reseed_golden_sms(serial: str) -> bool:
    if not (os.path.exists(_GOLDEN_SMS_PROVIDER_SQL) and os.path.exists(_GOLDEN_FOSSIFY_DB)):
        logger.info("[redroid] golden SMS fixtures absent; skipping SMS reseed")
        return True
    try:
        with open(_GOLDEN_SMS_PROVIDER_SQL) as f:
            prov_sql = f.read()
        prov_sql = prov_sql.replace("INSERT INTO", "INSERT OR REPLACE INTO")
        r = _device_sqlite(serial, _SMS_PROVIDER_DB, prov_sql, timeout=60)
        if r.returncode != 0 and (r.stderr or "").strip():
            logger.warning(f"[redroid] provider SMS reseed warnings: {r.stderr.strip()[:200]}")

        _run(["adb", "-s", serial, "shell", "am", "force-stop", _SMS_FOSSIFY_PKG], timeout=30)
        fuid = (
            _run(
                ["adb", "-s", serial, "shell", "stat", "-c", "%u", f"/data/data/{_SMS_FOSSIFY_PKG}"]
            ).stdout.strip()
            or "0"
        )
        fdir = f"/data/data/{_SMS_FOSSIFY_PKG}/databases"
        _run(
            [
                "adb",
                "-s",
                serial,
                "push",
                _GOLDEN_FOSSIFY_DB,
                "/data/local/tmp/conversations_golden.db",
            ],
            timeout=60,
        )
        _run(
            [
                "adb",
                "-s",
                serial,
                "shell",
                f"mkdir -p {fdir}; cp /data/local/tmp/conversations_golden.db {fdir}/conversations.db; "
                f"rm -f {fdir}/conversations.db-wal {fdir}/conversations.db-shm; "
                f"chown {fuid}:{fuid} {fdir}/conversations.db; chmod 660 {fdir}/conversations.db; "
                f"rm -f /data/local/tmp/conversations_golden.db",
            ],
            timeout=30,
        )
        logger.info("[redroid] re-seeded golden SMS (provider + Fossify) after restore")
        return True
    except Exception as e:
        logger.error(f"[redroid] reseed_golden_sms failed: {e}")
        return False


def capture_golden_data() -> bool:
    container = _env("REDROID_CONTAINER", "redroid14-sandbox")
    volume = _env("REDROID_DATA_VOLUME", "redroid14-gms-data")
    baseline = _env("REDROID_DATA_BASELINE", "/root/redroid-data.tgz")
    mountpoint = _safe_data_mountpoint(volume)
    if not mountpoint:
        return False
    try:
        _run(["docker", "stop", container], timeout=120, check=True)
        r = _run(["tar", "czf", baseline, "-C", mountpoint, "."], timeout=1200)
        if not _start_redroid_container(container):
            return False
        if r.returncode != 0:
            logger.error(f"[redroid] failed to capture baseline: {r.stderr.strip()}")
            return False
        logger.info(f"[redroid] captured golden /data baseline -> {baseline}")
        return True
    except Exception as e:
        logger.error(f"[redroid] capture_golden_data failed: {e}")
        return False
