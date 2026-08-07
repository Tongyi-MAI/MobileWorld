#!/bin/bash
# Swap AOSP DocumentsUI for Google's DocumentsUI (the full Files manager:
# rename / copy to / move to / delete / compress). The two packages share provider
# authorities, so they cannot coexist — the AOSP *system* package must be removed
# (a per-user uninstall does not free the authority), not just hidden. redroid's
# /system is a writable overlay and ro.control_privapp_permissions=disable, so the
# Google APK drops in as a priv-app with no whitelist needed. Lives outside /data
# (so it survives per-task golden restores but is lost on container rm) -> applied
# here per container create. The caller reboots afterwards so PMS rescans /system.
set -u
DEV="${1:-emulator-5554}"
APK="${DOCUMENTSUI_GOOGLE_APK:-/opt/redroid/DocumentsUIGoogle.apk}"
DST=/system/priv-app/DocumentsUIGoogle/DocumentsUIGoogle.apk

[ -f "$APK" ] || { echo "[documentsui] $APK missing; skip"; exit 0; }

adb -s "$DEV" root >/dev/null 2>&1 || true
echo "[documentsui] swapping AOSP -> Google DocumentsUI (full file manager)"
adb -s "$DEV" shell rm -rf /system/priv-app/DocumentsUI /system/etc/permissions/com.android.documentsui.xml
adb -s "$DEV" shell mkdir -p /system/priv-app/DocumentsUIGoogle
adb -s "$DEV" push "$APK" "$DST" >/dev/null 2>&1 || { echo "[documentsui] push failed"; exit 1; }
adb -s "$DEV" shell chmod 644 "$DST"
echo "[documentsui] installed; PMS rescans on the entrypoint reboot"
