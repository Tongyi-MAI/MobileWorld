#!/bin/bash
# Install the smsnotifier helper app. redroid has no SIM, so injected inbound SMS
# (written straight into the telephony provider + Fossify DB by inject_inbound_sms)
# never trigger Fossify's SMS_DELIVER receiver and post no notification. This headless
# app posts a persistent SMS-style notification when broadcast; inject_inbound_sms
# fires that broadcast. A real-app notification survives the process exit (a shell
# `cmd notification post` does not). Idempotent; lives outside /data so it is lost on
# container rm -> re-applied here per (re)create.
set -u
DEV="${1:-emulator-5554}"
APK="${SMSNOTIFIER_APK:-/opt/redroid_assets/smsnotifier.apk}"
PKG=com.mobileworld.smsnotifier

[ -f "$APK" ] || { echo "[smsnotifier] $APK missing; skip"; exit 0; }

# Fast path: smsnotifier is baked into golden /data — skip reinstall on a fresh boot.
if [ "${FORCE_NOTIFIER_INSTALL:-0}" != "1" ] && [ -n "$(adb -s "$DEV" shell pm path "$PKG" 2>/dev/null | tr -d '\r')" ]; then
  echo "[smsnotifier] already installed (golden /data); skipping reinstall"
elif adb -s "$DEV" install -r -g "$APK" >/dev/null 2>&1 \
  || adb -s "$DEV" install -r "$APK" >/dev/null 2>&1; then
  :
else
  echo "[smsnotifier] install failed"; exit 0
fi
# POST_NOTIFICATIONS is a runtime permission on Android 13+; without it the
# notification is silently dropped.
adb -s "$DEV" shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || true
echo "[smsnotifier] installed $PKG"
