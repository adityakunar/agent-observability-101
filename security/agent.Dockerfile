# Image for the sandboxed agent. Dependencies install at build time; at run time the
# container has no internet route except through the egress proxy.
FROM python:3.14.4-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends make git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home agent
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_NO_SYNC=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/work/src \
    PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml uv.lock /opt/app/
RUN cd /opt/app && uv sync --locked --no-install-project && rm -rf /tmp/uv-cache
USER agent
WORKDIR /work
