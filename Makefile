# Common development tasks. Run `make help` to list them.

VENV   ?= .venv
PYTHON := $(VENV)/bin/python
RUFF   := $(VENV)/bin/ruff
TAILWIND := $(VENV)/bin/tailwindcss
HOST   ?= 127.0.0.1
PORT   ?= 8000
CSS_IN  := assets/tailwind.css
CSS_OUT := articles/static/articles/app.css

.DEFAULT_GOAL := help
.PHONY: help install migrate runserver test lint format css css-watch check deploy-check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

$(PYTHON):
	uv venv $(VENV)

install: $(PYTHON) ## Create the virtualenv and install all dependencies
	uv pip install --python $(VENV) -r requirements-dev.txt

migrate: ## Apply database migrations
	$(PYTHON) manage.py migrate

runserver: migrate ## Run the development server (HOST=127.0.0.1 PORT=8000)
	$(PYTHON) manage.py runserver $(HOST):$(PORT)

test: ## Run the test suite (pass extra args with ARGS=, e.g. ARGS=social)
	$(PYTHON) manage.py test $(ARGS)

lint: ## Check code style and common errors (ruff + Django checks)
	$(RUFF) check .
	$(RUFF) format --check .
	$(PYTHON) manage.py check
	$(PYTHON) manage.py makemigrations --check --dry-run

format: ## Format the code and auto-fix lint issues
	$(RUFF) format .
	$(RUFF) check --fix .

css: ## Rebuild the Tailwind stylesheet
	$(TAILWIND) -i $(CSS_IN) -o $(CSS_OUT) --minify

css-watch: ## Rebuild the Tailwind stylesheet on every change
	$(TAILWIND) -i $(CSS_IN) -o $(CSS_OUT) --watch

check: lint test ## Run lint and tests (what to run before committing)

deploy-check: ## Run Django's production checks with production-like settings
	DJANGO_DEBUG=0 DJANGO_SECRET_KEY=$$($(PYTHON) -c "import secrets; print(secrets.token_urlsafe(64))") \
		DJANGO_ALLOWED_HOSTS=example.com $(PYTHON) manage.py check --deploy
