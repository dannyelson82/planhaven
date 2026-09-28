# syntax=docker/dockerfile:1
# PlanHaven all-in-one image (ADR 0002): s6-overlay supervising PostgreSQL + pgvector and the app.
# Build from the repository root:  docker build -f docker/Dockerfile .
# Base images are pinned by digest; Dependabot proposes updates.

ARG PYTHON_IMAGE=python:3.14-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
ARG NODE_IMAGE=node:24-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424

ARG S6_VERSION=3.2.3.2
ARG PG_MAJOR=18
ARG TARGETARCH

FROM ${UV_IMAGE} AS uv

# ------------------------------------------------------------------ frontend build
FROM ${NODE_IMAGE} AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
# The user guide is shown on the Help page (imported at build time from ../docs/user-guide).
COPY docs/user-guide/ /src/docs/user-guide/
RUN npm run build

# ------------------------------------------------------------------ backend virtualenv
FROM ${PYTHON_IMAGE} AS backend
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src/backend
# The plugin SDK is a path dependency of the backend (ARCHITECTURE.md §14.2).
COPY sdk/python /src/sdk/python
# Dependencies first (cached layer), exactly as pinned in uv.lock, without dev tools.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md /src/README.md
COPY backend/app ./app
RUN uv sync --locked --no-dev --no-editable

# ------------------------------------------------------------------ s6-overlay (checksum-verified)
FROM ${PYTHON_IMAGE} AS s6-base
RUN apt-get update \
 && apt-get install -y --no-install-recommends xz-utils \
 && rm -rf /var/lib/apt/lists/*
ARG S6_VERSION
ADD --checksum=sha256:5379750ed30a84bbd2e2dd74847ba6b5bd29cd0b2e3ea2ec58049b57eb2eda12 \
    https://github.com/just-containers/s6-overlay/releases/download/v${S6_VERSION}/s6-overlay-noarch.tar.xz /tmp/

FROM s6-base AS s6-amd64
ARG S6_VERSION
ADD --checksum=sha256:e6befcc96a437a3831386ecfc51808c5d3e939dc5fe3c02ae9284599e8aa2408 \
    https://github.com/just-containers/s6-overlay/releases/download/v${S6_VERSION}/s6-overlay-x86_64.tar.xz /tmp/s6-arch.tar.xz

FROM s6-base AS s6-arm64
ARG S6_VERSION
ADD --checksum=sha256:b17f17a82e7a515c682a91edaf2ffdabb73f891981b6c1fd712115693a2f8b4c \
    https://github.com/just-containers/s6-overlay/releases/download/v${S6_VERSION}/s6-overlay-aarch64.tar.xz /tmp/s6-arch.tar.xz

FROM s6-${TARGETARCH} AS s6
RUN mkdir /s6root \
 && tar -C /s6root -Jxpf /tmp/s6-overlay-noarch.tar.xz \
 && tar -C /s6root -Jxpf /tmp/s6-arch.tar.xz

# ------------------------------------------------------------------ runtime
FROM ${PYTHON_IMAGE}
# The release version (from the git tag); shown to signed-in users on the Account page.
ARG PLANHAVEN_VERSION=dev
ENV PLANHAVEN_VERSION=${PLANHAVEN_VERSION}
ARG PG_MAJOR

LABEL org.opencontainers.image.title="PlanHaven" \
      org.opencontainers.image.description="Self-hosted project manager: from idea to done." \
      org.opencontainers.image.source="https://github.com/dannyelson82/planhaven" \
      org.opencontainers.image.licenses="Apache-2.0"

# PostgreSQL + pgvector from the official PostgreSQL apt repository. The signing key is
# committed in the repo; CI checks its fingerprint (B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8).
# Debian's package would create a default cluster on install; we disable that and create our
# own cluster in /config at first boot.
COPY docker/pgdg-archive-key.asc /usr/share/keyrings/pgdg-archive-key.asc
RUN set -eu; \
    mkdir -p /etc/postgresql-common; \
    echo 'create_main_cluster = false' > /etc/postgresql-common/createcluster.conf; \
    printf '%s\n' \
      'Types: deb' \
      'URIs: https://apt.postgresql.org/pub/repos/apt' \
      'Suites: trixie-pgdg' \
      'Components: main' \
      'Signed-By: /usr/share/keyrings/pgdg-archive-key.asc' \
      > /etc/apt/sources.list.d/pgdg.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      "postgresql-${PG_MAJOR}" "postgresql-${PG_MAJOR}-pgvector" \
      libheif-examples libheif-plugin-libde265; \
    # iPhone (HEIC) photos are decoded by libheif's separate command-line tool (ADR 0010:
    # a separate program, LGPL). Only the decoder plugin: the x265 encoder plugin is GPL and
    # must never be in the image.
    if dpkg-query -W -f='${Package}\n' | grep -q x265; then \
      echo "GPL x265 found in the image" >&2; exit 1; \
    fi; \
    rm -rf /var/lib/apt/lists/* /var/lib/postgresql/*; \
    # Debian generates a "snakeoil" TLS keypair on install. PostgreSQL here has no network
    # listener and never uses TLS, and a private key must not ship in a public image.
    rm -f /etc/ssl/private/ssl-cert-snakeoil.key /etc/ssl/certs/ssl-cert-snakeoil.pem; \
    # pip is not needed at runtime (the app's packages are installed by uv at build time);
    # removing it also removes its vendored libraries from the scan surface.
    rm -rf /usr/local/bin/pip* /usr/local/lib/python3*/site-packages/pip \
      /usr/local/lib/python3*/site-packages/pip-*.dist-info \
      /usr/local/lib/python3*/ensurepip

COPY --from=s6 /s6root/ /
COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /src/frontend/dist /app/frontend
# Bundled plugins; only admin-enabled ones are ever imported (ARCHITECTURE.md §14.7).
COPY plugins/ /app/plugins/
COPY docker/rootfs/ /

ENV PATH="/app/.venv/bin:/usr/lib/postgresql/${PG_MAJOR}/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PUID=99 \
    PGID=100 \
    TZ=UTC \
    # Stop the container if any startup service fails (fail closed), and support --read-only.
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=180000 \
    S6_READ_ONLY_ROOT=1 \
    S6_KEEP_ENV=0

VOLUME ["/config", "/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=4).status == 200 else 1)"]

# s6-overlay's /init runs as root only to prepare directories and then drops privileges:
# PostgreSQL runs as the `postgres` user and the app as PUID:PGID (SECURITY.md §7.13).
ENTRYPOINT ["/init"]
