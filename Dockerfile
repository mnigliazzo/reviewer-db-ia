ARG DOCKER_REGISTRY
FROM ${DOCKER_REGISTRY:+$DOCKER_REGISTRY/}python:3.12-slim

ARG http_proxy
ARG https_proxy
ARG no_proxy
ENV http_proxy=${http_proxy} \
    https_proxy=${https_proxy} \
    no_proxy=${no_proxy}

# Install uv compiler via pip
RUN pip install uv==0.3.0

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Crear el virtual environment de antemano
RUN uv venv /app/.venv

# 🟢 CORRECCIÓN: Copiar el código directo en /app en lugar de crear una subcarpeta
COPY . /app

# Instalar el proyecto en modo editable (-e) apoderándose del directorio actual
RUN uv pip install -e .

# El WORKDIR se queda en /app, así que todo es consistente
CMD ["python", "-m", "src.main", "--help"]

# Limpieza final de variables de proxy
ENV http_proxy="" https_proxy="" no_proxy=""