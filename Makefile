.PHONY: up down logs ps smoke ch migrate topics reset urls

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
	docker compose exec clickhouse clickhouse-client --user $(CH_USER) --password $(CH_PASS) -d irm

topics:    ## buat topic yang belum ada
	docker compose run --rm topics-init

migrate: topics   ## jalankan semua SQL di clickhouse/init (idempotent, IF NOT EXISTS)
	@for f in clickhouse/init/*.sql; do \
	  echo ">> $$f"; \
	  docker compose exec -T clickhouse clickhouse-client --user $(CH_USER) --password $(CH_PASS) --multiquery < $$f || exit 1; \
	done

urls:      ## tampilkan URL aplikasi
	@echo "Peta    : http://localhost:8000"
	@echo "API docs: http://localhost:8000/docs"
	@echo "Grafana : http://$$(hostname -I | awk '{print $$1}'):3001"
	@echo "Console : http://localhost:8080"

reset:     ## HAPUS semua data (volume)
	docker compose down -v
