.PHONY: help build run down ps logs clean prepare-delta clean-tmp

# Configuración de variables del Pipeline
ENV_FILE=--env-file .env.jali
FOLDER_TMP=./tmp/db-script
FILE_VERSION=current_db_version.txt

help:
	@echo ""
	@echo "  make build             — Construye las imágenes Docker"
	@echo "  make run               — Ejecuta la auditoría IA sobre el delta actual"
	@echo "  make clean             — Limpia contenedores y residuos temporales"
	@echo ""

build:
	docker compose $(ENV_FILE) build reviewer

prepare-delta:
	@echo "🚀 Iniciando preparación del entorno delta..."
	@rm -rf $(FOLDER_TMP)
	
	@export GIT_USERNAME=$$(grep GIT_USER .env.jali | cut -d'=' -f2 | tr -d '\r\n'); \
	 B64_PASS=$$(grep GIT_PASSWORD .env.jali | cut -d'=' -f2 | tr -d '\r\n'); \
	 export GIT_PASSWORD=$$(echo "$$B64_PASS" | tr -d '\r\n' | base64 -d); \
	 BRANCH=$$(grep GIT_BRANCH .env.jali | cut -d'=' -f2 | tr -d '\r\n'); \
	 URL=$$(grep REPO_URL .env.jali | cut -d'=' -f2 | tr -d '\r\n'); \
	 \
	 echo "📥 Clonando rama $$BRANCH de forma segura..."; \
	 git clone --depth 1 -b "$$BRANCH" --single-branch "$$URL" $(FOLDER_TMP)

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
	@echo "🤖 Lanzando agente de IA sobre el delta de migración..."
	@# 🟢 Volvemos a inyectar $(ENV_FILE) para que Docker tenga todas sus variables
	docker compose $(ENV_FILE) run --rm reviewer
	@$(MAKE) clean-tmp

down: 
	docker compose $(ENV_FILE) down

clean-tmp:
	@echo "🧹 Eliminando archivos temporales del repositorio clonado..."
	@rm -rf $(FOLDER_TMP)

clean: clean-tmp
	docker compose $(ENV_FILE) down -v --remove-orphans