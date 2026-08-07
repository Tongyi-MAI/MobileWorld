#!/bin/sh
# setup_vibrator.sh — idempotently install the no-op (example) AIDL vibrator HAL
# onto the redroid14-sandbox device so hasVibrator()==true (DeskClock vibrate toggle, etc).
#
# Persistence model: /vendor changes survive docker stop/start + restore_golden_data
# (which only wipes /data) but are LOST on docker rm / recreate_redroid.sh.
# Re-run this script after any container recreate, then reboot the device.
#
# REQUIRED pieces (all discovered necessary on 2026-06-07):
#   1. /vendor/bin/hw/android.hardware.vibrator-service.example  (HAL binary, 0755)
#   2. /vendor/lib64/android.hardware.vibrator-V2-ndk.so         (HAL interface lib; the
#        vendor binary's linker cannot reach /system/lib64, so without this the service
#        crash-loops "CANNOT LINK ... not found" and hangs boot ~100s)
#   3. /vendor/etc/init/vendor.vibrator-default.rc               (init service def, 0644)
#   4. /vendor/etc/vintf/manifest/android.hardware.vibrator-service.example.xml (0644)
#        MUST declare BOTH IVibrator/default AND IVibratorManager/default — the example
#        main.cpp AServiceManager_addService()s both; an undeclared interface => the
#        addService returns status=-3 and the service aborts (Check failed status==STATUS_OK).
set -e
DEV="${1:-emulator-5554}"
ADB="adb -s $DEV"
ABI="$($ADB shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r')"
ASSET_ROOT="${REDROID_ASSET_ROOT:-/opt/redroid_assets}"
case "$ABI" in
  arm64-v8a) ASSET="$ASSET_ROOT/vibrator/android.hardware.vibrator-service.example-arm64" ;;
  x86_64)    ASSET="$ASSET_ROOT/vibrator/android.hardware.vibrator-service.example" ;;
  *) echo "setup_vibrator.sh: unsupported device ABI: ${ABI:-unknown}" >&2; exit 1 ;;
esac
STAGE="/data/local/tmp/android.hardware.vibrator-service.example"

if [ ! -f "$ASSET" ]; then
  echo "setup_vibrator.sh: missing $ABI HAL asset: $ASSET" >&2
  exit 1
fi

$ADB root >/dev/null 2>&1 || true
$ADB shell mount -o remount,rw / 2>/dev/null || true

# 1. binary
$ADB push "$ASSET" "$STAGE"
$ADB shell cp "$STAGE" /vendor/bin/hw/android.hardware.vibrator-service.example
$ADB shell chmod 755 /vendor/bin/hw/android.hardware.vibrator-service.example
$ADB shell chown root:shell /vendor/bin/hw/android.hardware.vibrator-service.example

# 2. HAL interface lib into the vendor namespace
$ADB shell cp /system/lib64/android.hardware.vibrator-V2-ndk.so /vendor/lib64/android.hardware.vibrator-V2-ndk.so
$ADB shell chmod 644 /vendor/lib64/android.hardware.vibrator-V2-ndk.so
$ADB shell chown root:root /vendor/lib64/android.hardware.vibrator-V2-ndk.so

# 3. init .rc — written on-device via a base64 blob to avoid any quoting issues
RC_B64='c2VydmljZSB2ZW5kb3IudmlicmF0b3ItZGVmYXVsdCAvdmVuZG9yL2Jpbi9ody9hbmRyb2lkLmhhcmR3YXJlLnZpYnJhdG9yLXNlcnZpY2UuZXhhbXBsZQogICAgY2xhc3MgaGFsCiAgICB1c2VyIHN5c3RlbQogICAgZ3JvdXAgc3lzdGVtCg=='
echo "$RC_B64" | $ADB shell "base64 -d > /vendor/etc/init/vendor.vibrator-default.rc"
$ADB shell chmod 644 /vendor/etc/init/vendor.vibrator-default.rc
$ADB shell chown root:root /vendor/etc/init/vendor.vibrator-default.rc

# 4. VINTF fragment (BOTH interfaces) — likewise via base64
XML_B64='PG1hbmlmZXN0IHZlcnNpb249IjEuMCIgdHlwZT0iZGV2aWNlIj4KICAgIDxoYWwgZm9ybWF0PSJhaWRsIj4KICAgICAgICA8bmFtZT5hbmRyb2lkLmhhcmR3YXJlLnZpYnJhdG9yPC9uYW1lPgogICAgICAgIDx2ZXJzaW9uPjI8L3ZlcnNpb24+CiAgICAgICAgPGZxbmFtZT5JVmlicmF0b3IvZGVmYXVsdDwvZnFuYW1lPgogICAgPC9oYWw+CiAgICA8aGFsIGZvcm1hdD0iYWlkbCI+CiAgICAgICAgPG5hbWU+YW5kcm9pZC5oYXJkd2FyZS52aWJyYXRvcjwvbmFtZT4KICAgICAgICA8dmVyc2lvbj4yPC92ZXJzaW9uPgogICAgICAgIDxmcW5hbWU+SVZpYnJhdG9yTWFuYWdlci9kZWZhdWx0PC9mcW5hbWU+CiAgICA8L2hhbD4KPC9tYW5pZmVzdD4K'
echo "$XML_B64" | $ADB shell "base64 -d > /vendor/etc/vintf/manifest/android.hardware.vibrator-service.example.xml"
$ADB shell chmod 644 /vendor/etc/vintf/manifest/android.hardware.vibrator-service.example.xml
$ADB shell chown root:root /vendor/etc/vintf/manifest/android.hardware.vibrator-service.example.xml

echo "setup_vibrator.sh: files installed. Reboot the device, then verify:"
echo "  $ADB shell cmd vibrator_manager list   # expect: 1"
