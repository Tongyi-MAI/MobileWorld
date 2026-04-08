# Dockerfile.aw — AndroidWorld-enabled MobileWorld image
#
# Merges docker/Dockerfile + docker/Dockerfile.update into a single build.
# Requires: extracted AVD directory at docker/Pixel_8_API_34_x86_64.avd/
#   (contains aw_init_state snapshot with all AW apps pre-installed)
#
# Build:
#   docker build -f docker/Dockerfile.aw -t mobile_world:aw-apps .
#
# Pre-requisite — extract AVD from existing aw-apps image:
#   docker create --name avd_extract mobile_world:aw-apps true
#   docker cp avd_extract:/root/.android/avd/Pixel_8_API_34_x86_64.avd docker/Pixel_8_API_34_x86_64.avd
#   docker rm avd_extract

FROM cruizba/ubuntu-dind:latest

ENV PYTHONUNBUFFERED=1 \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_HOME=/opt/android-sdk

ENV PATH="$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$PATH"

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    bash \
    vim \
    wget \
    curl \
    unzip \
    ca-certificates \
    libnss3 \
    libstdc++6 \
    libgcc-s1 \
    libpulse-dev \
    openjdk-17-jdk \
    scrcpy \
    python3 \
    python3-pip \
    ffmpeg \
    socat && \
    update-ca-certificates && \
    ln -sf python3 /usr/bin/python && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Pin setuptools < 81 to keep pkg_resources (needed by supervisord for DinD)
# aiohttp: needed by ws_adb_proxy.py (WebSocket ADB proxy for web-scrcpy viewer)
RUN pip install --break-system-packages --no-cache "setuptools<81" uv aiohttp

RUN mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools" && \
    cd "$ANDROID_SDK_ROOT/cmdline-tools" && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip -O cmdline-tools.zip && \
    mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools/latest" && \
    unzip -q cmdline-tools.zip -d "/tmp" && \
    mv /tmp/cmdline-tools/* "$ANDROID_SDK_ROOT/cmdline-tools/latest" && \
    rm -f cmdline-tools.zip && \
    yes | sdkmanager --licenses >/dev/null && \
    wget https://edgedl.me.gvt1.com/edgedl/android/repository/emulator-linux_x64-14214601.zip -O /tmp/emulator.zip && \
    unzip /tmp/emulator.zip -d $ANDROID_SDK_ROOT/ && \
    sdkmanager "platform-tools" "build-tools;34.0.0" "platforms;android-34" "system-images;android-34;google_apis;x86_64" && \
    rm -rf $ANDROID_SDK_ROOT/emulator-2 2>/dev/null || true && \
    rm /tmp/emulator.zip

COPY pyproject.toml uv.lock /app/service/

# AVD with aw_init_state snapshot (all AndroidWorld apps pre-installed)
ENV AVD_NAME=Pixel_8_API_34_x86_64
COPY docker/${AVD_NAME}.avd /root/.android/avd/${AVD_NAME}.avd
COPY docker/${AVD_NAME}.ini /root/.android/avd/${AVD_NAME}.ini

COPY docker/skins /root/.android/avd/skins
COPY docker/adbkey docker/adbkey.pub /root/.android/
COPY docker/start_emulator.sh /app/docker/start_emulator.sh
RUN chmod +x /app/docker/start_emulator.sh

# web-scrcpy viewer (Apache 2.0 licensed, built from panda-web-scrcpy)
COPY docker/web-scrcpy /app/web-scrcpy
COPY docker/ws_adb_proxy.py /app/docker/ws_adb_proxy.py

# Source code
COPY src /app/service/src
COPY README.md /app/service/README.md

# AndroidWorld submodule + emulator compatibility patch
COPY resources/android_world/ /app/service/resources/android_world/
COPY docker/patches/aw_browser.py /app/service/resources/android_world/android_world/task_evals/single/browser.py
COPY docker/patches/aw_audio_recorder.py /app/service/resources/android_world/android_world/task_evals/single/audio_recorder.py
COPY docker/patches/aw_expense.py /app/service/resources/android_world/android_world/task_evals/single/expense.py
COPY docker/patches/aw_actuation.py /app/service/resources/android_world/android_world/env/actuation.py

# Patched Clipper APK (original targets SDK 0, incompatible with API 34)
COPY docker/apks/clipper.apk /app/docker/apks/clipper.apk
# A11y forwarder APK (AccessibilityService → gRPC, replaces UIAutomator dump)
COPY docker/apks/accessibility_forwarder.apk /app/docker/apks/accessibility_forwarder.apk

# Python dependencies — MobileWorld + AndroidWorld
RUN cd /app/service && uv sync --no-cache && \
    uv pip install setuptools --python /app/service/.venv/bin/python && \
    cd /app/service/resources/android_world && \
    uv pip install -e . --no-deps --no-build-isolation --python /app/service/.venv/bin/python

# Docker resources (mattermost, mastodon)
COPY docker/mattermost-docker /app/mattermost-docker-bk
COPY docker/mastodon-docker /app/mastodon-docker-bk
RUN chown -R 991:991 /app/mastodon-docker-bk
COPY docker/images /app/images
RUN chown -R 2000:2000 /app/mattermost-docker-bk/volumes/app/mattermost

# AndroidWorld setup scripts (for future re-setup if needed)
COPY docker/setup_android_world_apps.sh /app/docker/setup_android_world_apps.sh
COPY docker/setup_aw_apps.py /app/docker/setup_aw_apps.py
RUN chmod +x /app/docker/setup_android_world_apps.sh

WORKDIR /app/service
COPY docker/entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:6800/health || exit 1

ENTRYPOINT ["entrypoint.sh"]
CMD tail -f /var/log/emulator.log /var/log/server.log /var/log/dockerd.err.log
