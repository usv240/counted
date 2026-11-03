FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PORT=8080
# Tracing is off unless the deployment turns it on (deploy/ecs_redeploy.py sets OTEL_SDK_DISABLED=false and the rest).
ENV OTEL_SDK_DISABLED=true
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY web ./web
COPY data ./data
COPY evals ./evals
RUN uv sync --frozen --no-dev && useradd -r -u 1001 counted && chown -R counted /app
USER counted
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8080/v1/health')"
CMD ["/app/.venv/bin/opentelemetry-instrument", "/app/.venv/bin/counted-api"]
