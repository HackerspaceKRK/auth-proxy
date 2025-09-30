# Python app
FROM python:3.12-slim-bookworm

ENV POETRY_VERSION=2.1.3
ENV PYTHONBUFFERED=1
ENV POETRY_INSTALLER_MAX_WORKERS=1
ENV POETRY_VIRTUALENVS_IN_PROJECT=false
ENV POETRY_VIRTUALENVS_CREATE=false

RUN apt update \
    && apt install -y \
      curl \
      libffi-dev  \
    && curl -sSL https://install.python-poetry.org | python - --version ${POETRY_VERSION} \
    && apt remove -y --autoremove --purge curl libffi-dev \
    && apt clean && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:$PATH"

WORKDIR /code

COPY ./pyproject.toml ./poetry.lock /code/
RUN poetry install --no-interaction --no-root --only=main

ARG BUILD_COMMIT_SHA
ENV BUILD_COMMIT_SHA=${BUILD_COMMIT_SHA:-}

#RUN if [ "${BUILD_COMMIT_SHA}" = "localdev" ]; then \
#    poetry install --no-interaction --no-root --only=dev; \
#    fi

COPY . /code
ENV PYTHONUNBUFFERED=0

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]

