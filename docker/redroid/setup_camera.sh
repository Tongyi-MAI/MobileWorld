#!/bin/bash
# Idempotent redroid camera setup: install the mock camera app and make it the sole camera
# (stock com.android.camera2 has a black viewfinder on redroid's software-GL stack).
# The mock app mimics the camera UI, shows a mock-video viewfinder, and on shutter saves a
# JPEG to /sdcard/Pictures (+ MediaStore) and handles IMAGE_CAPTURE (EXTRA_OUTPUT, RESULT_OK).
# Persists across recreate_redroid.sh via the redroid14-gms-data volume; this is for fresh hosts.
DEV="${1:-emulator-5554}"
APK="/opt/redroid_assets/mockcamera.apk"
adb -s "$DEV" root >/dev/null 2>&1; sleep 1
# Fast path: mockcamera is baked into golden /data — skip reinstall on a fresh boot.
if [ "${FORCE_CAMERA_INSTALL:-0}" != "1" ] && [ -n "$(adb -s "$DEV" shell pm path com.mobileworld.mockcamera 2>/dev/null | tr -d '\r')" ]; then
  echo "mockcamera already installed (golden /data); skipping reinstall"
elif ! adb -s "$DEV" install -r -g "$APK" >/dev/null 2>&1; then
  adb -s "$DEV" uninstall com.mobileworld.mockcamera >/dev/null 2>&1 || true
  adb -s "$DEV" install -g "$APK"
fi
adb -s "$DEV" shell pm disable-user --user 0 com.android.camera2 >/dev/null 2>&1 || true
echo "camera installed: $(adb -s "$DEV" shell pm path com.mobileworld.mockcamera 2>/dev/null | tr -d '\r')"
echo "STILL_IMAGE_CAMERA -> $(adb -s "$DEV" shell cmd package resolve-activity --brief -a android.media.action.STILL_IMAGE_CAMERA 2>/dev/null | tail -1 | tr -d '\r')"
