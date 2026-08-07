FROM ubuntu:24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG MATTERMOST_UID=2000
ARG MATTERMOST_GID=2000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        mailcap \
        media-types \
        poppler-utils \
        tidy \
        tzdata \
        unrtf \
        wv \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${MATTERMOST_GID}" mattermost \
    && useradd --uid "${MATTERMOST_UID}" --gid mattermost --home-dir /mattermost --no-create-home mattermost

COPY mattermost-team-10.5.2-linux-arm64.tar.gz /tmp/mattermost.tar.gz
RUN tar -xzf /tmp/mattermost.tar.gz -C / \
    && rm /tmp/mattermost.tar.gz \
    && chown -R mattermost:mattermost /mattermost

COPY --chown=mattermost:mattermost entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

USER mattermost
WORKDIR /mattermost
ENV PATH="/mattermost/bin:${PATH}"

EXPOSE 8065 8067 8074 8075
VOLUME ["/mattermost/config", "/mattermost/data", "/mattermost/logs", "/mattermost/plugins", "/mattermost/client/plugins"]

HEALTHCHECK --interval=30s --timeout=10s \
    CMD curl -f http://localhost:8065/api/v4/system/ping || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["mattermost"]
