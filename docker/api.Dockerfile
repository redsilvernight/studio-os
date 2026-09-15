FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
COPY packages ./packages
COPY services ./services

RUN uv sync --frozen --no-dev --all-packages

ENV PATH="/app/.venv/bin:$PATH"

# Default to the API entrypoint; docker-compose overrides `command:` for the
# mcp service to run studio_mcp.server instead.
CMD ["uvicorn", "studio_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
