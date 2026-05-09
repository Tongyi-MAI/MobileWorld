#!/bin/bash

set -e

# Normalize HTTP proxy env vars and always exempt the emulator→host loopback
# (10.0.2.2) and local services. Without NO_PROXY=10.0.2.2,localhost the
# in-container backend hops (Mattermost on 8065, Mastodon, etc.) would route
# through the user's external proxy and break.
PROXY="${http_proxy:-${HTTP_PROXY:-}}"
if [ -n "$PROXY" ]; then
    export http_proxy="$PROXY"  HTTP_PROXY="$PROXY"
    export https_proxy="${https_proxy:-${HTTPS_PROXY:-$PROXY}}"
    export HTTPS_PROXY="$https_proxy"
    USER_NO_PROXY="${no_proxy:-${NO_PROXY:-}}"
    export no_proxy="10.0.2.2,127.0.0.1,localhost,::1${USER_NO_PROXY:+,$USER_NO_PROXY}"
    export NO_PROXY="$no_proxy"
    echo "INFO: outbound HTTP proxy = $PROXY (NO_PROXY=$NO_PROXY)"
fi

# disable ipv6 otherwise sim card will be disabled in android emulator
# related issue: https://issuetracker.google.com/issues/215231636?pli=1
sysctl net.ipv6.conf.all.disable_ipv6=1

# Auto-detect the correct iptables backend for the host kernel.
# - Newer kernels (6.x+) may have dropped legacy iptable_nat → need iptables-nft
# - Older kernels may lack nf_tables → need iptables-legacy
# We try nft first (since it's the forward-looking choice), fall back to legacy.
if command -v update-alternatives &>/dev/null && command -v iptables-nft &>/dev/null; then
    if iptables-nft -L -n &>/dev/null; then
        update-alternatives --set iptables /usr/sbin/iptables-nft 2>/dev/null || true
        update-alternatives --set ip6tables /usr/sbin/ip6tables-nft 2>/dev/null || true
        echo "INFO: using iptables-nft backend (nftables kernel API available)"
    else
        update-alternatives --set iptables /usr/sbin/iptables-legacy 2>/dev/null || true
        update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || true
        echo "INFO: using iptables-legacy backend (nftables kernel API not available)"
    fi
fi

# located at /usr/local/bin/start-docker.sh
start-docker.sh

# Verify dockerd is actually functional (start-docker.sh only checks process existence,
# which can pass even if dockerd crashes shortly after with iptables errors)
DOCKER_READY_TIMEOUT=30
DOCKER_WAITED=0
while ! docker info &>/dev/null; do
    if [ $DOCKER_WAITED -ge $DOCKER_READY_TIMEOUT ]; then
        echo "ERROR: dockerd failed to become functional after ${DOCKER_READY_TIMEOUT}s" >&2
        echo "Check /var/log/dockerd.err.log for details." >&2
        if [ -f /var/log/dockerd.err.log ]; then
            echo "--- Last 20 lines of dockerd.err.log ---" >&2
            tail -20 /var/log/dockerd.err.log >&2
        fi
        echo "" >&2
        echo "Common cause: host kernel lacks iptable_nat module (kernel 6.x+)." >&2
        echo "Fix: ensure iptables-nft is the default backend, or load iptable_nat on host." >&2
        exit 1
    fi
    sleep 1
    ((DOCKER_WAITED++))
done
echo "INFO: dockerd is functional (verified via 'docker info')"

cd /app/images
for f in *.tar; do docker load -i "$f"; done

cd /app/service


# ENABLE_VNC is a legacy alias for ENABLE_VIEWER (VNC stack replaced by web-scrcpy)
if [ "${ENABLE_VNC:-false}" = "true" ] || [ "${ENABLE_VNC:-false}" = "1" ] || \
   [ "${ENABLE_VIEWER:-false}" = "true" ] || [ "${ENABLE_VIEWER:-false}" = "1" ]; then
    # web-scrcpy viewer: WebSocket ADB proxy + static frontend on port 7860
    python3 /app/docker/ws_adb_proxy.py \
        --adb-port 5555 --port 7860 --static /app/web-scrcpy \
        >> /var/log/viewer.log 2>&1 &
fi

# Dev mode (ENABLE_VNC kept as the dev-mode trigger for backward compatibility):
# sync extra deps and re-install AndroidWorld if present
if [ "${ENABLE_VNC:-false}" = "true" ] || [ "${ENABLE_VNC:-false}" = "1" ]; then
    uv sync --extra dev --no-cache
    if [ -d /app/service/resources/android_world ]; then
        cd /app/service/resources/android_world && \
        uv pip install -e . --no-deps --no-build-isolation --python /app/service/.venv/bin/python
        cd /app/service
    fi
fi
/app/docker/start_emulator.sh

# Start ADB relay in background to expose ADB on 0.0.0.0:5556
socat TCP-LISTEN:5556,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:5555 &
SOCAT_PID=$!

uv run mobile-world server --port 6800 >> /var/log/server.log 2>&1 &

# Execute specified command
"$@"