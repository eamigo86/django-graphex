.PHONY: help install migrate seed superuser run shell reset clean collectstatic test
.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install deps (uv) — uses the local library
	uv sync

migrate: ## Make + apply migrations (SQLite)
	uv run python manage.py makemigrations blog
	uv run python manage.py migrate

seed: ## Load demo data (user demo / demo12345, posts, comments, notes)
	uv run python manage.py seed

collectstatic: ## Collect static files into STATIC_ROOT (for production serving)
	uv run python manage.py collectstatic --noinput

superuser: ## Create your own superuser (for /admin login -> private queries)
	uv run python manage.py createsuperuser

run: ## Run the ASGI server (HTTP + WebSocket) at http://127.0.0.1:8000/graphql/
	uv run daphne -b 127.0.0.1 -p 8000 config.asgi:application

shell: ## Open a Django shell
	uv run python manage.py shell

test: ## Run the playground end-to-end tests (WS + SSE round-trips, schema, client)
	uv run --group test pytest -q --no-migrations

reset: ## Drop the SQLite db and re-migrate + re-seed
	rm -f db.sqlite3
	find blog/migrations -maxdepth 1 -type f -name '0*.py' -delete
	find blog/migrations -type d -name __pycache__ -prune -exec rm -rf {} +
	$(MAKE) migrate
	$(MAKE) seed

clean: ## Remove the db and caches
	rm -f db.sqlite3
	find . -type d -name __pycache__ -exec rm -rf {} +
