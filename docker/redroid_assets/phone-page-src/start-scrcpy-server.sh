#!/bin/bash
# Start (or restart) one ws-scrcpy "web" scrcpy server bound to the device's tcp:8886,
# fully detached so it survives the launching shell. The server version is read from the
# bundled ws-scrcpy dist (it drifts with upstream HEAD — e.g. 1.19-ws5 -> 1.19-ws7), so
# the server arg always matches what the client expects (a mismatch makes the jar abort).
#
# ws-scrcpy does NOT auto-spawn this server for the proxy-adb page; the phone-proxy calls
# this on demand when a viewer connects.
#
# Usage: start-scrcpy-server.sh [adb-device]   (default 127.0.0.1:5555)
set -u
D="${1:-127.0.0.1:5555}"
JAR="${SCRCPY_JAR:-/opt/ws-scrcpy/dist/vendor/Genymobile/scrcpy/scrcpy-server.jar}"
WS_DIST="${WS_SCRCPY_DIST:-/opt/ws-scrcpy/dist}"
LOG="${SCRCPY_LOG:-/var/log/scrcpy_8886.log}"

# version the ws-scrcpy client expects (auto-detected from its dist; fallback pinned)
VER="$(grep -rhoE '1\.[0-9]+-ws[0-9]+' "$WS_DIST" 2>/dev/null | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')"
VER="${VER:-1.19-ws7}"

case "$D" in *:*) adb connect "$D" >/dev/null 2>&1 ;; esac

# kill any stale scrcpy server (match the cmdline — robust on 64-bit redroid where the
# process is app_process64, which `pidof app_process` would miss)
timeout 6 adb -s "$D" shell pkill -f com.genymobile.scrcpy.Server >/dev/null 2>&1

adb -s "$D" push "$JAR" /data/local/tmp/scrcpy-server.jar >/dev/null 2>&1
setsid adb -s "$D" shell \
  "CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / com.genymobile.scrcpy.Server $VER web ERROR 8886 true" \
  </dev/null >"$LOG" 2>&1 &
disown
echo "launched scrcpy $VER web server for $D (host pid $!, log $LOG)"
