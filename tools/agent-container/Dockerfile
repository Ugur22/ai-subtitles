# Isolated development container for autonomous Claude Code sessions on ai-subs.
#
# Built only by `bin/agent build`, from the tools/agent-container/ tree of origin/main (reviewed code).
# Trust split: everything this image installs is root-owned and read-only to the agent, which runs as `node`
# (uid 1000). bin/agent starts the container with every capability dropped, no-new-privileges and no sudo,
# so the agent can't change the firewall (applied from a separate short-lived container), the managed
# settings, the Claude Code install or these scripts. Pin the base image by digest before relying on it.
FROM node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

ARG CLAUDE_CODE_VERSION=2.1.331
ARG GRAPHIFY_VERSION=0.9.110
ARG SOURCE_COMMIT=unknown

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git gh jq make procps \
      python3 python3-venv python3-dev build-essential pkg-config ffmpeg \
      iptables ipset iproute2 dnsutils aggregate \
    && rm -rf /var/lib/apt/lists/*

# Installed as root, so the agent can run Claude Code but not replace it. Updates come from a rebuild.
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" && npm cache clean --force

# The repo's project hooks call graphify by its host path; the same path here keeps them working.
RUN python3 -m venv /opt/graphify \
    && /opt/graphify/bin/pip install --no-cache-dir "graphifyy==${GRAPHIFY_VERSION}" \
    && mkdir -p /Users/ugurertas/.local/bin \
    && ln -s /opt/graphify/bin/graphify /Users/ugurertas/.local/bin/graphify \
    && ln -s /opt/graphify/bin/graphify /usr/local/bin/graphify

# Explicit owner, and the directory made first: BuildKit gives an implicitly created parent the file's
# --chmod (0644, so nobody could enter it), and a tar context carries the builder's uid into the image.
RUN install -d -o root -g root -m 0755 /etc/claude-code
COPY --chown=root:root --chmod=0755 agent-session agent-checks.sh agent-verify init-firewall.sh git-credential-agent gh /usr/local/bin/
COPY --chown=root:root --chmod=0644 managed-settings.json /etc/claude-code/managed-settings.json
COPY --chown=root:root --chmod=0644 gitconfig /etc/gitconfig
RUN sha256sum /etc/claude-code/managed-settings.json | cut -d' ' -f1 > /etc/claude-code/managed-settings.sha256 \
    && echo "${SOURCE_COMMIT}" > /etc/agent-image-commit \
    && mkdir -p /work /home/node/.claude \
    && chown node:node /work /home/node/.claude

LABEL org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.title="ai-subs-agent"

ENV CLAUDE_CONFIG_DIR=/home/node/.claude \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    NPM_CONFIG_IGNORE_SCRIPTS=true \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

USER node
WORKDIR /work
CMD ["sleep", "infinity"]
