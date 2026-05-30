# IntentFrame B2B runtime image.
#
# One image, two roles (selected by the compose `command`):
#   * runtime : credential-vault (bootstrap) + supervisor (4 UDS services)
#   * edge    : network-facing HTTP/TLS proxy → the runtime's UDS sockets
#
# Build context is the repo root:
#     docker build -f deploy/prod/Dockerfile -t intentframe:local .

FROM python:3.14-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

# Non-root runtime user; sockets live under its home so a freshly
# initialised named volume inherits the right ownership.
RUN useradd --create-home --uid 10001 intentframe

WORKDIR /app
COPY . /app

# Resolve the uv workspace into /app/.venv (macOS-only deps are skipped
# on Linux via environment markers in pyproject.toml). The `hashicorp` extra
# pulls in hvac so the credential-vault service can use IF_VAULT_BACKEND=hashicorp.
RUN uv sync --no-dev --extra hashicorp \
 && chmod +x /app/deploy/prod/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    HOME=/home/intentframe \
    PYTHONUNBUFFERED=1 \
    INTENTFRAME_EXECUTOR_MODE=real \
    EXECUTOR_CONFIG=/app/executor/config/executor.yaml

USER intentframe
RUN mkdir -p /home/intentframe/.intentframe/run

# Default role is the runtime; compose overrides `command` for the edge.
ENTRYPOINT ["/app/deploy/prod/entrypoint.sh"]
