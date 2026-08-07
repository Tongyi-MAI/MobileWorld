#!/bin/bash
# Entrypoint for the MobileWorld V1-compatible redroid runtime image
# (mobile_world:v1-redroid).
#
# Topology: ONE privileged dind container. The inner dockerd runs redroid (the
# Android device) + mattermost/mastodon (on demand, per task). Redroid stays on
# inner docker0; a two-hop Unix-socket relay adapts adbd's isolated IPv6 listener
# to outer 127.0.0.1:5555 for adb's emulator-5554 auto-discovery.
# 10.0.2.2 is an IP alias on docker0 so the device reaches the backends at the
# exact addresses baked into golden /data.
#
# No QEMU, no KVM. binder comes from the HOST kernel (CONFIG_ANDROID_BINDERFS +
# binder_linux must be present on the build/run host); the dind mounts its own
# binderfs instance. Validated: nested redroid reaches boot_completed in ~3-9s
# once cgroup-v2 controllers are delegated in the dind subtree.
set -e

REDROID_IMAGE="${REDROID_IMAGE:-redroid/redroid:14.0.0_64only_mindthegapps}"
REDROID_CONTAINER="${REDROID_CONTAINER:-redroid14-sandbox}"
REDROID_DATA_VOLUME="${REDROID_DATA_VOLUME:-redroid14-gms-data}"
REDROID_DATA_BASELINE="${REDROID_DATA_BASELINE:-/opt/redroid-data.tgz}"
DEV="${ANDROID_DEVICE:-emulator-5554}"
REDROID_DNS1="${REDROID_DNS1:-8.8.8.8}"
REDROID_DNS2="${REDROID_DNS2:-8.8.4.4}"

log() { echo "[entrypoint] $*"; }

# --- uv: skip the runtime sync/rebuild by default ----------------------------------
# The venv is baked at build time (Dockerfile `uv sync`). Otherwise every `uv run`
# re-validates and rebuilds the editable mobile-world wheel in an isolated PEP517 build
# env, fetching hatchling from the index — which stampedes/hangs when many containers
# boot at once ("Building mobile-world @ file:///app/service"). Set MW_UV_SYNC=1 to
# force a runtime sync (e.g. after mounting changed deps).
if [ "${MW_UV_SYNC:-0}" = "1" ]; then
    log "MW_UV_SYNC=1: runtime uv sync enabled"
else
    export UV_NO_SYNC=1 UV_FROZEN=1
fi

# --- HTTP proxy normalization (always exempt 10.0.2.2 + local services) --------
PROXY="${http_proxy:-${HTTP_PROXY:-}}"
if [ -n "$PROXY" ]; then
    export http_proxy="$PROXY" HTTP_PROXY="$PROXY"
    export https_proxy="${https_proxy:-${HTTPS_PROXY:-$PROXY}}"
    export HTTPS_PROXY="$https_proxy"
    USER_NO_PROXY="${no_proxy:-${NO_PROXY:-}}"
    export no_proxy="10.0.2.2,127.0.0.1,localhost,::1${USER_NO_PROXY:+,$USER_NO_PROXY}"
    export NO_PROXY="$no_proxy"
    log "outbound HTTP proxy = $PROXY (NO_PROXY=$NO_PROXY)"
fi

# --- iptables backend auto-detect (nft vs legacy) for inner dockerd ------------
if command -v update-alternatives &>/dev/null && command -v iptables-nft &>/dev/null; then
    if iptables-nft -L -n &>/dev/null; then
        update-alternatives --set iptables /usr/sbin/iptables-nft 2>/dev/null || true
        update-alternatives --set ip6tables /usr/sbin/ip6tables-nft 2>/dev/null || true
    else
        update-alternatives --set iptables /usr/sbin/iptables-legacy 2>/dev/null || true
        update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || true
    fi
fi

# --- pre-extract golden /data in the BACKGROUND so it overlaps dockerd bring-up ---
# The ~4GB tar-xf is otherwise serial dead time before the volume seed; kick it off now
# and `wait` for it just before seeding. Only runs on a fresh container (GOLDEN_DIR empty).
GOLDEN_DIR="${REDROID_DATA_GOLDEN_DIR:-/opt/redroid-data-golden}"
EXTRACT_PID=""
if [ -f "$REDROID_DATA_BASELINE" ] && { [ ! -d "$GOLDEN_DIR" ] || [ -z "$(ls -A "$GOLDEN_DIR" 2>/dev/null)" ]; }; then
    log "pre-extracting golden /data -> $GOLDEN_DIR (background, one-time)"
    mkdir -p "$GOLDEN_DIR"
    ( tar xf "$REDROID_DATA_BASELINE" -C "$GOLDEN_DIR" ) &
    EXTRACT_PID=$!
fi

# --- start the inner dockerd and wait until it is functional -------------------
start-docker.sh
DOCKER_WAITED=0
while ! docker info &>/dev/null; do
    if [ $DOCKER_WAITED -ge 60 ]; then
        log "ERROR: dockerd failed to become functional after 60s"
        [ -f /var/log/dockerd.err.log ] && tail -20 /var/log/dockerd.err.log >&2
        exit 1
    fi
    sleep 1; ((DOCKER_WAITED++))
done
log "inner dockerd is functional"

# --- cgroup v2 delegation (the gating fix for nested redroid init) -------------
# cgroup2 forbids enabling controllers on a cgroup that holds processes directly,
# so move the dind's procs into a leaf, then delegate controllers to the subtree.
# Without this the nested redroid init exits 129 / services crash-loop.
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
    mkdir -p /sys/fs/cgroup/dind-init 2>/dev/null || true
    for p in $(cat /sys/fs/cgroup/cgroup.procs 2>/dev/null); do
        echo "$p" > /sys/fs/cgroup/dind-init/cgroup.procs 2>/dev/null || true
    done
    echo "+memory +io +cpu +cpuset +pids" > /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null \
        && log "cgroup delegated: $(cat /sys/fs/cgroup/cgroup.subtree_control)" \
        || log "WARN: cgroup delegation failed (nested redroid may not boot)"
fi

# --- ensure binderfs (host kernel must have binder_linux loaded) ---------------
modprobe binder_linux 2>/dev/null || true
if [ ! -e /dev/binderfs/binder-control ]; then
    mkdir -p /dev/binderfs
    mountpoint -q /dev/binderfs || mount -t binder binder /dev/binderfs
fi
if [ ! -e /dev/binderfs/binder ]; then
    /usr/local/sbin/binderfs_add /dev/binderfs/binder-control binder hwbinder vndbinder
fi
chmod 666 /dev/binderfs/binder /dev/binderfs/hwbinder /dev/binderfs/vndbinder 2>/dev/null || true
if [ ! -e /dev/binderfs/binder ]; then
    log "ERROR: binderfs unavailable — host kernel needs CONFIG_ANDROID_BINDERFS + binder_linux"
    exit 1
fi
if ! python3 -c 'fd = open("/dev/binderfs/binder", "r+b", buffering=0); fd.close()' 2>/dev/null; then
    log "ERROR: binder device exists but cannot be opened — bind-mount the host /dev/binderfs into this container"
    exit 1
fi
log "binderfs ready: $(ls /dev/binderfs 2>/dev/null | tr '\n' ' ')"

# --- images are baked into /var/lib/docker at build time (tars bind-mounted during
# build, never shipped in the image). If the baked store lacks the redroid image the
# build is broken — fail fast rather than silently hang later.
if ! docker image inspect "$REDROID_IMAGE" &>/dev/null; then
    log "FATAL: baked redroid image $REDROID_IMAGE missing from the inner docker store"
    docker images >&2
    exit 1
fi

# --- 10.0.2.2 alias on the inner docker0 bridge (host loopback equivalent) -----
ip addr del 10.0.2.2/32 dev docker0 2>/dev/null || true
ip addr add 10.0.2.2/32 dev docker0 2>/dev/null && log "10.0.2.2 aliased on docker0" \
    || log "WARN: could not add 10.0.2.2 alias on docker0"

# --- seed the redroid /data volume from the (background-extracted) golden dir ----
# Per-task restore_golden_data rsyncs from this staging dir (copies only what a task
# dirtied) instead of decompressing the 4GB baseline on every reset. baseline is zstd.
if [ -n "$EXTRACT_PID" ]; then
    log "waiting for background golden /data extract"
    wait "$EXTRACT_PID" || log "WARN: golden /data background extract failed"
fi
docker rm -f "$REDROID_CONTAINER" 2>/dev/null || true
docker volume create "$REDROID_DATA_VOLUME" >/dev/null
MP="$(docker volume inspect -f '{{.Mountpoint}}' "$REDROID_DATA_VOLUME")"
if [ -n "$MP" ] && [ -d "$GOLDEN_DIR" ] && [ -n "$(ls -A "$GOLDEN_DIR" 2>/dev/null)" ]; then
    log "seeding golden /data from $GOLDEN_DIR into $MP (rsync)"
    rsync -a --delete "$GOLDEN_DIR/" "$MP/"
elif [ -n "$MP" ] && [ -f "$REDROID_DATA_BASELINE" ]; then
    log "seeding golden /data from $REDROID_DATA_BASELINE into $MP (untar fallback)"
    find "$MP" -mindepth 1 -delete 2>/dev/null || true
    tar xf "$REDROID_DATA_BASELINE" -C "$MP"
fi

log "launching redroid container $REDROID_CONTAINER"
docker run -d --name "$REDROID_CONTAINER" --privileged --restart unless-stopped \
    -v /dev/binderfs/binder:/dev/binder \
    -v /dev/binderfs/hwbinder:/dev/hwbinder \
    -v /dev/binderfs/vndbinder:/dev/vndbinder \
    -v "$REDROID_DATA_VOLUME":/data \
    --shm-size 64m \
    "$REDROID_IMAGE" \
    androidboot.redroid_width=720 androidboot.redroid_height=1600 androidboot.redroid_dpi=280 \
    androidboot.redroid_fps=60 androidboot.redroid_gpu_mode=guest androidboot.use_memfd=true \
    androidboot.redroid_net_ndns=2 androidboot.redroid_net_dns1="$REDROID_DNS1" \
    androidboot.redroid_net_dns2="$REDROID_DNS2"

# adbd listens on an isolated IPv6 wildcard in this ARM build. Android netd also
# rejects ingress on Redroid's bridge address, so a normal Docker -p mapping is
# insufficient. Cross the network-namespace boundary with a Unix socket instead:
# outer 127.0.0.1:5555 -> Unix socket -> Redroid ::1:5555. Keeping Redroid bridged
# is essential because Android netd mutates a host network namespace and would
# otherwise break the outer MW/viewer port connectivity.
REDROID_PID="$(docker inspect -f '{{.State.Pid}}' "$REDROID_CONTAINER")"
if [ -z "$REDROID_PID" ] || [ "$REDROID_PID" = "0" ]; then
    log "ERROR: unable to resolve the Redroid container PID for the ADB relay"
    exit 1
fi
REDROID_ADB_SOCKET=/run/redroid-adbd.sock
rm -f "$REDROID_ADB_SOCKET"
nsenter -t "$REDROID_PID" -n \
    socat UNIX-LISTEN:"$REDROID_ADB_SOCKET",fork,unlink-early,mode=0666 TCP6:[::1]:5555 &
REDROID_ADB_UNIX_RELAY_PID=$!
echo "$REDROID_ADB_UNIX_RELAY_PID" > /run/redroid-adb-unix-relay.pid
for _ in $(seq 1 50); do
    [ -S "$REDROID_ADB_SOCKET" ] && break
    sleep 0.1
done
if [ ! -S "$REDROID_ADB_SOCKET" ]; then
    log "ERROR: Redroid ADB Unix relay did not create $REDROID_ADB_SOCKET"
    exit 1
fi
socat TCP4-LISTEN:5555,fork,reuseaddr,bind=127.0.0.1 \
    UNIX-CONNECT:"$REDROID_ADB_SOCKET" &
REDROID_ADB_TCP_RELAY_PID=$!
echo "$REDROID_ADB_TCP_RELAY_PID" > /run/redroid-adb-tcp-relay.pid
log "ADB relay started (redroid pid=$REDROID_PID, unix pid=$REDROID_ADB_UNIX_RELAY_PID, tcp pid=$REDROID_ADB_TCP_RELAY_PID)"

# --- wait for a stable boot; the first process may recover once with exit 129 --
adb start-server >/dev/null 2>&1 || true
cd /app/service
if ! uv run python - <<'PY'
import os

from mobile_world.runtime.utils.redroid_device import _wait_redroid_stable

ok = _wait_redroid_stable(
    os.environ.get("REDROID_CONTAINER", "redroid14-sandbox"),
    os.environ.get("ANDROID_DEVICE", "emulator-5554"),
    int(os.environ.get("REDROID_BOOT_TIMEOUT", "180")),
)
raise SystemExit(0 if ok else 1)
PY
then
    log "ERROR: $DEV did not reach a stable boot"
    docker logs "$REDROID_CONTAINER" 2>&1 | tail -25 >&2
    exit 1
fi
log "redroid boot_completed (device $DEV); asserting adb root"
adb -s "$DEV" root >/dev/null 2>&1 || true
sleep 2

# sys.boot_completed is set before all framework services are necessarily usable
# on this ARM build. Do not expose the MW server until controller construction can
# read a real viewport and the first task can safely drive package/activity/input.
android_framework_ready() {
    local service
    for service in package activity input window; do
        adb -s "$DEV" shell service check "$service" 2>/dev/null | grep -q found || return 1
    done
    adb -s "$DEV" shell wm size 2>/dev/null | grep -q 'Physical size:'
}
FRAMEWORK_WAITED=0
until android_framework_ready; do
    if [ "$FRAMEWORK_WAITED" -ge 120 ]; then
        log "ERROR: Android framework services did not become ready after 120s"
        exit 1
    fi
    sleep 2
    FRAMEWORK_WAITED=$((FRAMEWORK_WAITED+2))
done
log "Android framework ready ($(adb -s "$DEV" shell wm size 2>/dev/null | tr -d '\r'))"

# --- per-container app setup: camera/sms/notifier (install-skip if already baked into
# golden /data, #0) + SMS role + camera2-disable. The /vendor (vibrator) + /system
# (timeshift .so + init.zygote64.rc preload + Google DocumentsUI) patches are now BAKED
# into the redroid image, live at the FIRST boot (SELinux disabled) — no reboot needed.
for s in setup_camera setup_sms setup_notifier; do
    if [ -x "/opt/redroid/$s.sh" ]; then
        log "applying $s.sh"
        bash "/opt/redroid/$s.sh" "$DEV" || log "WARN: $s.sh failed (non-fatal)"
    fi
done
# --- benchmark time frame: shift the GUEST clock (not the host) via libtimeshift --
# host CLOCK_REALTIME stays real (concurrent eval + dashscope TLS); the guest and the
# in-container verifier are offset to REDROID_TARGET_DATETIME. Per-container, no host
# change — the redroid equivalent of the emulator's per-guest virtual RTC.
if [ "${REDROID_TIMESHIFT:-1}" = "1" ]; then
    # Anchor at NOON UTC, not midnight: midnight sits on the day boundary, so any device
    # timezone behind UTC (or a few seconds' drift) reads the previous day. Noon gives a
    # ±12h margin -> the date is robustly 2025-10-16 in any TZ (matches set_task_timeframe).
    TGT="${REDROID_TARGET_DATETIME:-2025-10-16 12:00:00 UTC}"
    TS_OFFSET=$(( $(date -u -d "$TGT" +%s) - $(date +%s) ))
    log "timeshift: target='$TGT' offset=${TS_OFFSET}s (host stays real)"
    echo "$TS_OFFSET" > /run/timeshift_offset    # read by the MW-server glibc shim
    bash /opt/redroid/setup_timeshift.sh "$DEV" "$TS_OFFSET" || log "WARN: setup_timeshift failed"
fi

# Applying a large offset can make Android recycle system_server once. Require
# the controller-facing framework to remain healthy before exposing :6800.
FRAMEWORK_WAITED=0
FRAMEWORK_STABLE=0
while [ "$FRAMEWORK_STABLE" -lt 10 ]; do
    if android_framework_ready; then
        FRAMEWORK_STABLE=$((FRAMEWORK_STABLE+2))
    else
        FRAMEWORK_STABLE=0
    fi
    if [ "$FRAMEWORK_WAITED" -ge 120 ]; then
        log "ERROR: Android framework did not stabilize after timeshift"
        exit 1
    fi
    sleep 2
    FRAMEWORK_WAITED=$((FRAMEWORK_WAITED+2))
done
log "Android framework stable after timeshift"

# NOTE (#7): the mandatory mid-entrypoint REBOOT is GONE. The /vendor (vibrator HAL) +
# /system (timeshift libtimeshift.so + init.zygote64.rc LD_PRELOAD + Google DocumentsUI
# priv-app, AOSP DocumentsUI removed) patches are baked into the redroid image, so they
# are live at the FIRST boot. Because DocumentsUI resolves from boot, Launcher3 no longer
# prunes the golden Files favorite (the launcher.db reseed is unnecessary) and DocumentsUI's
# golden /data is not orphaned (the list-view pref reseed is unnecessary). setup_timeshift
# above still sets the per-task offset prop; the baked zygote preload reads it within ~1s.

# --- reseed golden SMS (the provider re-purges on boot) -----------------------
# clock is handled by libtimeshift (guest) + the MW-server glibc shim, not set_host_clock.
cd /app/service
uv run python - <<'PY' || true
from mobile_world.runtime.utils import redroid_device
try:
    redroid_device.reseed_golden_sms("emulator-5554")
except Exception as e:
    print("reseed_golden_sms:", e)
try:
    redroid_device.reseed_launcher_shortcuts("emulator-5554")
except Exception as e:
    print("reseed_launcher_shortcuts:", e)
PY

# --- phone-page viewer on :7860 (ws-scrcpy skin + proxy + device scrcpy server)
# ws-scrcpy's native node-pty (pty.node) is built against Node 16 in the ws-builder
# stage, so it MUST run under Node 16 (node16) — Node 18 aborts with a NODE_MODULE_VERSION
# mismatch. The phone-proxy below is plain JS and runs fine on the default Node 18.
if [ -d /opt/ws-scrcpy ]; then
    WS_SCRCPY_PORT=8000 setsid bash -c 'cd /opt/ws-scrcpy && exec /usr/local/bin/node16 dist/index.js' >/var/log/ws-scrcpy.log 2>&1 &
    # the proxy starts the device scrcpy server ON DEMAND when a viewer connects and
    # stops it when idle (no eager start, no watchdog) — so nothing churns the device
    # against per-task reboots when nobody is watching.
    PHONE_PROXY_PORT=7860 WS_SCRCPY_PORT=8000 setsid node /opt/redroid-phone-proxy/redroid-phone-proxy.js >/var/log/phone-proxy.log 2>&1 &
fi

# --- ADB relay so the host can reach the device adb on 0.0.0.0:5556 ------------
socat TCP-LISTEN:5556,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:5555 &

# --- MobileWorld server on :6800 (verifier clock shifted to match the guest) ---
TS_SO="${TIMESHIFT_GLIBC_SO:-/usr/local/lib/libtimeshift.so}"
if [ "${REDROID_TIMESHIFT:-1}" = "1" ] && [ -f "$TS_SO" ]; then
    LD_PRELOAD="$TS_SO" TIMESHIFT_OFFSET_FILE=/run/timeshift_offset \
        uv run mobile-world server --port 6800 >> /var/log/server.log 2>&1 &
else
    uv run mobile-world server --port 6800 >> /var/log/server.log 2>&1 &
fi

log "ready: redroid + MW server up; mattermost/mastodon start on demand per task"
touch /var/log/redroid.log
"$@"
