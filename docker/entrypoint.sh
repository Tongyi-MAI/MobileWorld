#!/bin/bash

# disable ipv6 otherwise sim card will be disabled in android emulator
# related issue: https://issuetracker.google.com/issues/215231636?pli=1
sysctl net.ipv6.conf.all.disable_ipv6=1
# located at /usr/local/bin/start-docker.sh
start-docker.sh


cd /app/images
for f in *.tar; do docker load -i "$f"; done

cd /app/service


if [ "${ENABLE_VNC:-false}" = "true" ] || [ "${ENABLE_VNC:-false}" = "1" ]; then
    /app/docker/start_novnc.sh
    # assuming dev mode
    uv sync --extra dev --no-cache
else
    uv run mobile-world viewer --port 7860 &
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