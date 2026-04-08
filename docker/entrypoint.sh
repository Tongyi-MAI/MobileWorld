#!/bin/bash

# disable ipv6 otherwise sim card will be disabled in android emulator
# related issue: https://issuetracker.google.com/issues/215231636?pli=1
sysctl net.ipv6.conf.all.disable_ipv6=1
# located at /usr/local/bin/start-docker.sh
start-docker.sh


cd /app/images
for f in *.tar; do docker load -i "$f"; done

cd /app/service


if [ "${ENABLE_VIEWER:-false}" = "true" ] || [ "${ENABLE_VIEWER:-false}" = "1" ]; then
    # web-scrcpy viewer: WebSocket ADB proxy + static frontend on port 7860
    python3 /app/docker/ws_adb_proxy.py \
        --adb-port 5555 --port 7860 --static /app/web-scrcpy \
        >> /var/log/viewer.log 2>&1 &
fi

# Dev mode: sync extra deps and re-install AndroidWorld
if [ "${DEV_MODE:-false}" = "true" ] || [ "${DEV_MODE:-false}" = "1" ]; then
    uv sync --extra dev --no-cache
    if [ -d /app/service/resources/android_world ]; then
        cd /app/service/resources/android_world && \
        uv pip install -e . --no-deps --no-build-isolation --python /app/service/.venv/bin/python
        cd /app/service
    fi
fi
# Clean stale emulator lock files (left over from docker commit of running containers)
find /root/.android/avd/ -name '*.lock' -type f -delete 2>/dev/null

/app/docker/start_emulator.sh

# Start ADB relay in background to expose ADB on 0.0.0.0:5556
socat TCP-LISTEN:5556,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:5555 &
SOCAT_PID=$!

uv run mobile-world server --port 6800 >> /var/log/server.log 2>&1 &

# Execute specified command
"$@"