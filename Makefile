.PHONY: up down logs ps smoke ch migrate topics reset urls batch-up batch-down airflow-pass llm-up llm-pull llm-eval

CH_USER := $(shell grep -E '^CLICKHOUSE_USER=' .env | cut -d= -f2)
CH_PASS := $(shell grep -E '^CLICKHOUSE_PASSWORD=' .env | cut -d= -f2)

up:        ## build & jalankan semua service
	docker compose up -d --build

down:      ## stop semua service (data tetap aman)
	docker compose down

logs:      ## log producer, dq, api
	docker compose logs -f --tail=100 producer-earthquake producer-hotspot producer-airquality dq api

ps:
	docker compose ps

smoke:     ## cek end-to-end
	bash scripts/smoke_test.sh

ch:        ## buka clickhouse-client
	@docker compose exec clickhouse clickhouse-client --user $(CH_USER) --password $(CH_PASS) -d irm

topics:    ## buat topic yang belum ada
	docker compose run --rm topics-init

migrate: topics   ## jalankan semua SQL di clickhouse/init (idempotent, IF NOT EXISTS)
	@for f in clickhouse/init/*.sql; do \
	  echo ">> $$f"; \
	  docker compose exec -T clickhouse clickhouse-client --user $(CH_USER) --password $(CH_PASS) --multiquery < $$f || exit 1; \
	done

batch-up:  ## jalankan Airflow (scraper berita, Fase 3)
	docker compose --profile batch up -d --build

batch-down:
	docker compose --profile batch stop airflow airflow-db

airflow-pass: ## password admin Airflow (user: admin)
	@docker compose --profile batch exec airflow cat /opt/airflow/standalone_admin_password.txt; echo

LLM_MODEL ?= $(or $(shell grep -E '^LLM_MODEL=' .env | cut -d= -f2),qwen2.5:3b)

llm-up:    ## jalankan Ollama (GPU)
	docker compose --profile llm up -d ollama

llm-pull:  ## download model (default dari .env LLM_MODEL; override: make llm-pull LLM_MODEL=gemma3:4b)
	docker compose --profile llm exec ollama ollama pull $(LLM_MODEL)

llm-eval:  ## uji LLM pada 15 berita terbaru (override: make llm-eval LLM_MODEL=...)
	docker compose --profile batch exec -e LLM_MODEL=$(LLM_MODEL) airflow python /opt/airflow/dags/llm_lib.py --eval 15 --model $(LLM_MODEL)

urls:      ## tampilkan URL aplikasi
	@echo "Peta    : http://localhost:8000"
	@echo "API docs: http://localhost:8000/docs"
	@echo "Grafana : http://$$(hostname -I | awk '{print $$1}'):3001"
	@echo "Console : http://localhost:8080"
	@echo "Airflow : http://$$(hostname -I | awk '{print $$1}'):8081  (user admin, password: make airflow-pass)"

reset:     ## HAPUS semua data (volume)
	docker compose down -v
