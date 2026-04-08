ARG DOCKER_REGISTRY
FROM $DOCKER_REGISTRY/python:3.12-slim

ARG http_proxy
ARG https_proxy
ARG no_proxy

# Install uv compiler via pip to avoid ghcr.io DNS issues in corporate networks
RUN pip install uv==0.3.0

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Crear el virtual environment de antemano
RUN uv venv /app/.venv

# Copiar el código del reviewer
COPY . /app/reviewer-db-ia

# Instalar reviewer en el venv
RUN uv pip install -e /app/reviewer-db-ia

WORKDIR /app/reviewer-db-ia

CMD ["python", "-m", "src.main", "--help"]
