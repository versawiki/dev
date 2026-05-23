# Multi-stage Docker build for the versawiki-orchestrator.
#
# Stage 1: install dependencies into a fat builder image
# Stage 2: copy only what we need into a slim runtime image
#
# Image runs as a non-root user. Volumes:
#   /var/lib/versawiki-orchestrator/repo    — local clone of versawiki/dev
#   /var/lib/versawiki-orchestrator/audit   — SQLite audit DB
#
# Exposed port: 8088 (control API). Use the docker-compose snippet in the
# deploy guide to put this behind nginx + Cloudflare if you want it on the
# public internet at orchestrator.versawiki.com.

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src

# Install the package + its runtime deps into /install. We use --target
# so the runtime stage can simply copy the directory.
RUN pip install --upgrade pip && \
    pip install --target=/install ".[test]"

# Compile claude-agent-sdk's bundled CLI in this builder stage. The SDK
# ships a Node-based CLI that's downloaded at install time.

# ---------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    VW_ORCH_REPO_WORKDIR=/var/lib/versawiki-orchestrator/repo \
    VW_ORCH_AUDIT_DB_PATH=/var/lib/versawiki-orchestrator/audit.sqlite

# git and ca-certificates are runtime requirements (the agent shells out
# to git for clone/commit/push). nodejs is required by the claude-agent-sdk
# bundled CLI.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git ca-certificates curl nodejs && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 1100 versawiki && \
    mkdir -p /var/lib/versawiki-orchestrator/repo && \
    chown -R versawiki:versawiki /var/lib/versawiki-orchestrator

WORKDIR /app
COPY --from=builder /install /usr/local/lib/python3.12/site-packages
COPY --chown=versawiki:versawiki src ./src

USER versawiki
EXPOSE 8088

# Healthcheck hits the control API. Requires the bearer token, but since
# Docker's HEALTHCHECK can't easily auth, we accept 401 as "alive" — the
# process is responding, just refusing unauthorised calls.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fs -o /dev/null -w "%{http_code}" http://localhost:8088/control/status | grep -qE "^(200|401)$"

CMD ["python", "-m", "versawiki_orchestrator.main"]
