.PHONY: help build run run-docker run-local down ps logs clean prepare-delta clean-tmp install check-env

# Configuración de variables del Pipeline
ENV_FILE_NAME := .env
ENV_FILE      := --env-file $(ENV_FILE_NAME)
FOLDER_TMP=./tmp/db-script
FILE_VERSION=current_db_version.txt

# Modo de ejecución de `make run`: docker (default) | local.
# Prioridad: variable en línea de comandos > MODE en .env > docker.
MODE := $(strip $(or $(MODE),$(shell awk -F= '/^MODE=/{sub(/[ \t#\r].*/,"",$$2); print $$2; exit}' $(ENV_FILE_NAME) 2>/dev/null),docker))
ifeq ($(filter $(MODE),docker local),)
$(error MODE inválido: '$(MODE)'. Valores válidos: docker | local)
endif

help:
	@echo ""
	@echo "  make install           — Instala deps con uv"
	@echo "  make build             — Construye las imágenes Docker"
	@echo "  make run               — Auditoría IA sobre el delta actual (MODE=$(MODE))"
	@echo "  make run MODE=local    — Igual, pero corriendo el CLI en el venv local (via run.sh)"
	@echo "  make run MODE=docker   — Igual, pero dentro del contenedor"
	@echo "  make clean             — Limpia contenedores y residuos temporales"
	@echo ""

install:
	uv pip install -e .

check-env:
	@test -f $(ENV_FILE_NAME) || { \
		echo "❌ Falta $(ENV_FILE_NAME). Copiá el template:  cp .env.example .env"; \
		exit 1; }

build: check-env
	docker compose $(ENV_FILE) build reviewer

prepare-delta: check-env
	@echo "🚀 Iniciando preparación del entorno delta..."
	@rm -rf $(FOLDER_TMP)
	
	@export GIT_USERNAME=$$(grep GIT_USER $(ENV_FILE_NAME) | cut -d'=' -f2 | tr -d '\r\n'); \
	 B64_PASS=$$(grep GIT_PASSWORD $(ENV_FILE_NAME) | cut -d'=' -f2 | tr -d '\r\n'); \
	 export GIT_PASSWORD=$$(echo "$$B64_PASS" | tr -d '\r\n' | base64 -d); \
	 BRANCH=$$(grep GIT_BRANCH $(ENV_FILE_NAME) | cut -d'=' -f2 | tr -d '\r\n'); \
	 URL=$$(grep REPO_URL $(ENV_FILE_NAME) | cut -d'=' -f2 | tr -d '\r\n'); \
	 \
	 echo "📥 Clonando rama $$BRANCH de forma segura..."; \
	 git -c core.longpaths=true clone --depth 1 -b "$$BRANCH" --single-branch "$$URL" $(FOLDER_TMP)

	@# Filtramos asegurando el listado correcto usando rutas nativas de directorios
	@CURRENT_VERSION=$$(cat $(FOLDER_TMP)/$(FILE_VERSION) | tr -d '\r\n '); \
	CUR_YEAR=$$(echo $$CURRENT_VERSION | cut -d'/' -f1 | tr -d '\r\n '); \
	CUR_TS=$$(echo $$CURRENT_VERSION | cut -d'/' -f2 | tr -d '\r\n '); \
	\
	if [ -z "$$CUR_YEAR" ] || [ -z "$$CUR_TS" ]; then \
		echo "❌ ERROR: No se pudo determinar la versión actual de la DB."; \
		exit 1; \
	fi; \
	\
	echo "🔍 Versión DB Actual -> Año: [$$CUR_YEAR] | Timestamp: [$$CUR_TS]"; \
	\
	cd $(FOLDER_TMP) && for year_path in *; do \
		if [ -d "$$year_path" ]; then \
			if echo "$$year_path" | grep -Eq '^[0-9]+$$'; then \
				if [ "$$year_path" -lt "$$CUR_YEAR" ]; then \
					echo "🗑️  Borrando año antiguo: $$year_path"; \
					rm -rf "$$year_path"; \
				elif [ "$$year_path" -eq "$$CUR_YEAR" ]; then \
					cd "$$year_path" && for ts_path in *; do \
						if [ -d "$$ts_path" ] && echo "$$ts_path" | grep -Eq '^[0-9]+$$'; then \
							if [ "$$ts_path" -le "$$CUR_TS" ]; then \
								echo "🗑️  Borrando migración antigua: $$year_path/$$ts_path"; \
								rm -rf "$$ts_path"; \
							else \
								echo "📦 Conservando delta nuevo: $$year_path/$$ts_path"; \
							fi \
						fi \
					done && cd ..; \
					if [ -z "$$(ls -A $$year_path 2>/dev/null)" ]; then rm -rf "$$year_path"; fi; \
				fi \
			else \
				echo "🗑️  Borrando carpeta no-migración: $$year_path"; \
				rm -rf "$$year_path"; \
			fi \
		fi \
	done
	@echo "✅ Filtro completado. Carpetas remanentes listas en $(FOLDER_TMP)"

run: prepare-delta
	@$(MAKE) --no-print-directory run-$(MODE)
	@$(MAKE) --no-print-directory clean-tmp

run-docker:
	@echo "🤖 Lanzando agente de IA (docker) sobre el delta de migración..."
	@# 🟢 Volvemos a inyectar $(ENV_FILE) para que Docker tenga todas sus variables
	docker compose $(ENV_FILE) run --rm reviewer

run-local:
	@echo "🤖 Lanzando agente de IA (local / venv) sobre el delta de migración..."
	@# run.sh lee .env, elige el python del venv y arma los flags del CLI.
	@bash run.sh

down: 
	docker compose $(ENV_FILE) down

clean-tmp:
	@echo "🧹 Eliminando archivos temporales del repositorio clonado..."
	@rm -rf $(FOLDER_TMP)

clean: clean-tmp
	docker compose $(ENV_FILE) down -v --remove-orphans