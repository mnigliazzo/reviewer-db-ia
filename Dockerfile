ARG DOCKER_REGISTRY
FROM ${DOCKER_REGISTRY:+$DOCKER_REGISTRY/}python:3.12-slim

ARG http_proxy
ARG https_proxy
ARG no_proxy
ENV http_proxy=${http_proxy} \
    https_proxy=${https_proxy} \
    no_proxy=${no_proxy}

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"
# Dentro del contenedor los scripts a revisar se montan acá (ver docker-compose.yml).
ENV SCRIPTS_PATH=/app/scripts_review
WORKDIR /app

# uv como instalador
RUN pip install uv==0.3.0

# Crear el virtual environment de antemano
RUN uv venv /app/.venv

# Copiar el código (el WORKDIR se queda en /app)
COPY . /app

# Instalar el proyecto en modo editable
RUN uv pip install -e .

# El mismo entrypoint que la ejecución local: run.py lee el entorno (inyectado por
# docker-compose con --env-file) y arma los flags del CLI. En el contenedor `python`
# ya es el del venv (PATH), así que no re-ejecuta.
CMD ["python", "run.py"]

# Limpieza final de variables de proxy
ENV http_proxy="" https_proxy="" no_proxy=""
