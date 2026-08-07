#!/bin/sh
# setup_timeshift.sh — install the bionic CLOCK_REALTIME offset shim and global-preload
# it into zygote, so the guest shows the benchmark frame (e.g. 2025-10-16) while the
# HOST clock stays real. Per-container, no host clock change — the redroid equivalent
# of the QEMU emulator's per-guest virtual RTC. Mirrors setup_vibrator.sh.
#
# Persistence: /system/lib64 .so + the init.zygote64.rc edit survive device reboot but
# are LOST on docker rm — re-run per container, BEFORE the post-/vendor reboot so the
# preload activates on that boot.
#
# args: DEV (default emulator-5554), OFFSET seconds (guest_wallclock - host_realtime).
# Apps/system_server read the offset from prop persist.sys.timeshift_off (re-read 1/s),
# so the eval can retune the frame per-task at runtime with a single setprop.
set -e
DEV="${1:-emulator-5554}"
OFFSET="${2:-0}"
ADB="adb -s $DEV"
ABI="$($ADB shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r')"
ASSET_ROOT="${REDROID_ASSET_ROOT:-/opt/redroid_assets}"
case "$ABI" in
  arm64-v8a) SO="$ASSET_ROOT/timeshift/libtimeshift-arm64.so" ;;
  x86_64)    SO="$ASSET_ROOT/timeshift/libtimeshift.so" ;;
  *) echo "setup_timeshift.sh: unsupported device ABI: ${ABI:-unknown}" >&2; exit 1 ;;
esac
RC="/system/etc/init/hw/init.zygote64.rc"

if [ ! -f "$SO" ]; then
  echo "setup_timeshift.sh: missing $ABI bionic shim: $SO" >&2
  exit 1
fi

$ADB root >/dev/null 2>&1 || true

# 1. .so into /system/lib64 (reachable by the system linker namespace; /vendor is not)
$ADB push "$SO" /data/local/tmp/libtimeshift.so
$ADB shell su 0 cp /data/local/tmp/libtimeshift.so /system/lib64/libtimeshift.so
$ADB shell su 0 chmod 644 /system/lib64/libtimeshift.so

# 2. offset: property (primary, retunable per-task) + file fallback (best-effort;
#    printf, not echo, so a leading '-' in a negative offset isn't taken as a flag)
$ADB shell su 0 setprop persist.sys.timeshift_off "$OFFSET"
$ADB shell "printf '%s' '$OFFSET' > /data/local/tmp/timeshift_offset" 2>/dev/null || true
$ADB shell su 0 chmod 644 /data/local/tmp/timeshift_offset 2>/dev/null || true

# 3. add `setenv LD_PRELOAD ...` to the zygote service (idempotent). Edit with the
#    container's GNU sed then push back — on-device toybox sed 'a' is unreliable.
HAS=$($ADB shell su 0 grep -c libtimeshift "$RC" 2>/dev/null | tr -d '\r')
if [ "$HAS" = "0" ]; then
    TMP="$(mktemp)"
    $ADB shell su 0 cat "$RC" > "$TMP"
    sed -i "/^service zygote /a\\    setenv LD_PRELOAD /system/lib64/libtimeshift.so" "$TMP"
    $ADB push "$TMP" /data/local/tmp/zygote.rc >/dev/null
    $ADB shell su 0 cp /data/local/tmp/zygote.rc "$RC"
    rm -f "$TMP"
fi
echo "setup_timeshift.sh: offset=${OFFSET}s; .so + zygote preload installed (reboot to activate)."
