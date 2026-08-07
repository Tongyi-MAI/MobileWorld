SHELL := /usr/bin/env bash

.PHONY: up restart down logs seed clean status backup restore \
	migrate assets import-db import-media db-up db-down

# lunch Mastodon
up:
	@echo "==> starting services..."
	docker compose up -d --remove-orphans
	@echo "==> services status:"
	docker compose ps

restart:
	@echo "==> restarting services..."
	docker compose restart
	@echo "==> services status:"
	docker compose ps

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

# generate sample data, details in scripts/seed.sh
seed:
	@bash scripts/seed.sh

# dangerous: delete containers and volumes
clean:
	@echo "==> stopping & removing all volumes ..."
	docker compose down -v

status:
	docker compose ps

# ========= restore =========
db-up:
	docker compose up -d db
	@sleep 3

db-down:
	docker compose stop db

# import DB（Postgres backup）— data/mastodon.sql.gz rollback to Postgres
import-db:
	@test -f data/mastodon.sql.gz || (echo "ERR: data/mastodon.sql.gz not found"; exit 1)
	@echo "==> (Re)creating database ..."
	docker compose exec -T db \
		bash -lc 'export PGPASSWORD="$$POSTGRES_PASSWORD"; \
		          dropdb --if-exists "$$POSTGRES_DB" -U "$$POSTGRES_USER"; \
		          createdb "$$POSTGRES_DB" -U "$$POSTGRES_USER"'
	@echo "==> importing SQL dump into $$POSTGRES_DB ..."
	gunzip -c data/mastodon.sql.gz | docker compose exec -T db \
		bash -lc 'export PGPASSWORD="$$POSTGRES_PASSWORD"; \
		          psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# import media volume（media rollback to media volume）
import-media:
	@test -f data/system.tar.gz || (echo "ERR: data/system.tar.gz not found"; exit 1)
	@echo "==> restoring media volume (media) ..."
	docker run --rm \
		-u 991:991 \
		-v mastodon-docker_media:/data \
		-v "$$(pwd)/data:/backup" \
		busybox sh -lc 'rm -rf /data/* && tar xzf /backup/system.tar.gz -C /data'

# ensure DB schema is up-to-date
# safe to run even if already up-to-date
migrate:
	docker compose run --rm web bash -lc "RAILS_ENV=production bundle exec rails db:migrate"

# restore
# steps: stop app services -> db-up -> import-db -> import-media -> up (full stack) -> migrate
restore:
	@echo "==> shutting down all services ..."
	docker compose down
	@echo "==> starting db service ..."
	@$(MAKE) db-up
	@$(MAKE) import-db
	@$(MAKE) import-media
	@echo "==> starting full stack..."
	docker compose up -d
	@echo "==> migrating to current schema (safe if already up-to-date)..."
	@$(MAKE) migrate
	@echo "==> restore complete. Services status:"
	@docker compose ps

# ========= backup =========
# backup, for fixture maintenance
# output:
# - data/mastodon.sql.gz  (Postgres dump)
# - data/system.tar.gz    (media volume tar)
backup:
	@echo "==> shutdown app services ..."
	docker compose down
	@echo "==> starting db service ..."
	@$(MAKE) db-up
	@mkdir -p data
	@echo "==> dumping PostgreSQL to data/mastodon.sql.gz ..."
	docker compose exec -T db \
		bash -lc 'export PGPASSWORD="$$POSTGRES_PASSWORD"; pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' \
	| gzip -9 > data/mastodon.sql.gz
	@echo "==> archiving media volume to data/system.tar.gz ..."
	docker run --rm \
		-v mastodon-docker_media:/data:ro \
		-v "$$(pwd)/data:/backup" \
		busybox sh -lc 'cd /data && tar czf /backup/system.tar.gz .'
	@echo "==> backup done:"
	@ls -lh data/mastodon.sql.gz data/system.tar.gz
