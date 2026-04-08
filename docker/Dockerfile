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
    xvfb \
    x11vnc \
    openbox \
    novnc \
    websockify \
    socat && \
    update-ca-certificates && \
    ln -sf python3 /usr/bin/python && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Pin setuptools < 81 to keep pkg_resources (needed by supervisord for DinD)
RUN pip install --break-system-packages --no-cache "setuptools<81" uv

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

ENV AVD_NAME=Pixel_8_API_34_x86_64
COPY docker/${AVD_NAME}.avd /root/.android/avd/${AVD_NAME}.avd
COPY docker/${AVD_NAME}.ini /root/.android/avd/${AVD_NAME}.ini


COPY docker/skins /root/.android/avd/skins
COPY docker/adbkey docker/adbkey.pub /root/.android/
COPY docker/start_emulator.sh /app/docker/start_emulator.sh
RUN chmod +x /app/docker/start_emulator.sh
COPY src /app/service/src
COPY README.md /app/service/README.md

RUN cd /app/service && \
    uv sync --no-cache

# Copy additional resources for mattermost
COPY docker/mattermost-docker /app/mattermost-docker-bk
# for mastodon
COPY docker/mastodon-docker /app/mastodon-docker-bk
RUN chown -R 991:991 /app/mastodon-docker-bk

COPY docker/images /app/images
# Set permissions
RUN chown -R 2000:2000 /app/mattermost-docker-bk/volumes/app/mattermost


WORKDIR /app/service
COPY docker/entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:6800/health || exit 1

ENTRYPOINT ["entrypoint.sh"]
CMD tail -f /var/log/emulator.log /var/log/server.log /var/log/dockerd.err.log
