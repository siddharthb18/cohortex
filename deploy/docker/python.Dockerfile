# One image recipe for every Python component in the uv workspace.
# Build from the repo root, e.g.:
#   docker build -f deploy/docker/python.Dockerfile --build-arg PACKAGE=cohortex-agent-service \
#     --build-arg MODULE=cohortex_agent -t cohortex/agent-service .
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY . .
ARG PACKAGE
RUN uv sync --frozen --no-dev --package "${PACKAGE}"

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 app
COPY --from=build /opt/venv /opt/venv
COPY contracts /app/contracts
COPY prompts /app/prompts
COPY db /app/db
ENV PATH="/opt/venv/bin:${PATH}" PYTHONUNBUFFERED=1 \
    COHORTEX_CONTRACTS_DIR=/app/contracts COHORTEX_PROMPTS_DIR=/app/prompts
WORKDIR /app
USER app
ARG MODULE
ENV MODULE=${MODULE}
CMD ["sh", "-c", "exec python -m ${MODULE}"]
