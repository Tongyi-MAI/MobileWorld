#!/bin/bash
# Idempotent redroid SMS-send setup: ensure the patched Fossify Messages build is
# installed and holds the default-SMS role. Patched so the agent's compose+Send lands
# a row in content://sms/sent even though redroid has no cellular radio.
# (Persists automatically across recreate_redroid.sh via the redroid14-gms-data volume;
#  this script is for fresh volumes / fresh hosts / snapshot restores.)
DEV="${1:-emulator-5554}"
APK="/opt/redroid_assets/fossify-patched.apk"
adb -s "$DEV" root >/dev/null 2>&1; sleep 1
# Fast path: the patched fossify is now baked into golden /data (/data/app), so a fresh
# boot already has it registered — skip the ~28s reinstall+dexopt. FORCE_SMS_INSTALL=1
# (or a fresh/legacy golden lacking it) falls back to the full install.
if [ "${FORCE_SMS_INSTALL:-0}" != "1" ] && [ -n "$(adb -s "$DEV" shell pm path org.fossify.messages 2>/dev/null | tr -d '\r')" ]; then
  echo "fossify already installed (golden /data); skipping reinstall"
elif ! adb -s "$DEV" install -r -g "$APK" >/dev/null 2>&1; then
  echo "in-place update failed (signature change) -> uninstall+install"
  adb -s "$DEV" uninstall org.fossify.messages >/dev/null 2>&1 || true
  adb -s "$DEV" install -g "$APK"
fi
adb -s "$DEV" shell cmd role add-role-holder android.app.role.SMS org.fossify.messages >/dev/null 2>&1 || true
adb -s "$DEV" shell appops set org.fossify.messages WRITE_SMS allow >/dev/null 2>&1 || true
echo "installed: $(adb -s "$DEV" shell pm path org.fossify.messages 2>/dev/null | tr -d '\r')"
echo "SMS role holder: $(adb -s "$DEV" shell cmd role get-role-holders android.app.role.SMS 2>/dev/null | tr -d '\r')"
