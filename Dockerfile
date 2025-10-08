# Python app
FROM python:3.12-slim-bookworm

ENV UV_VERSION=2.1.3
ENV PYTHONBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/venv

RUN apt update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.0 /uv /uvx /bin/

WORKDIR /code

COPY ./pyproject.toml ./uv.lock /code/
RUN uv sync --locked

ARG BUILD_COMMIT_SHA
ENV BUILD_COMMIT_SHA=${BUILD_COMMIT_SHA:-}

COPY . /code
ENV PYTHONUNBUFFERED=0

CMD ["uv", "run", "--no-sync", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
