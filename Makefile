# Shortcuts for developers. Coolify never runs make; it reads docker-compose.yml.
#
# Unlike the company template, `down` keeps .env: until Infisical is set up it is your
# real configuration, not a generated copy, so deleting it would lose your keys.

COMPOSE := docker compose -f docker-compose.yml -f docker-compose.override.yml
DEV_COMPOSE := $(COMPOSE) -f docker-compose.dev.yml
A2F_DIR := deploy/a2f
A2F_NETWORK := mari-a2f_default
# An installed pre-commit if there is one; otherwise pipx fetches it for the run.
PRE_COMMIT := $(shell command -v pre-commit 2>/dev/null || echo "pipx run pre-commit")

.PHONY: setup dev prod a2f down lint check

setup:  ## once per clone: install the commit hooks, create .env, install frontend packages
	command -v pre-commit >/dev/null || pipx install pre-commit
	pre-commit install
	test -f .env || cp .env.example .env
	cd frontend && npm ci

dev: a2f  ## start the kiosk with live reload (:3000, :8010): code changes apply without a rebuild
	@# Checked now, not when make starts, so the first run joins a network it just created.
	$(DEV_COMPOSE) $$(docker network inspect $(A2F_NETWORK) >/dev/null 2>&1 \
	  && echo "-f docker-compose.a2f.yml") up -d --build

prod: a2f  ## build and start the production images locally, as Coolify would run them
	$(COMPOSE) $$(docker network inspect $(A2F_NETWORK) >/dev/null 2>&1 \
	  && echo "-f docker-compose.a2f.yml") up -d --build

a2f:    ## start lipsync if this machine can (dev and prod run this first)
	@# Same rule as scripts/dev.sh: lipsync needs a GPU and deploy/a2f/.env (NGC_API_KEY).
	@# Without them the kiosk still runs, with a still mouth.
	@if [ -f $(A2F_DIR)/.env ]; then \
	  (cd $(A2F_DIR) && docker compose up -d) \
	    || echo "a2f: failed to start; continuing without lipsync"; \
	else \
	  echo "a2f: $(A2F_DIR)/.env missing; running without lipsync"; \
	fi

down:   ## stop everything (keeps .env; the A2F container is stopped, not removed, so it restarts fast)
	$(COMPOSE) down
	@if [ -f $(A2F_DIR)/.env ]; then (cd $(A2F_DIR) && docker compose stop); fi

lint:   ## run every check on every file (the same hooks that run on commit and on PRs)
	$(PRE_COMMIT) run --all-files

check:  ## the deeper checks before a PR: tests, snapshots, types, import layers (activate .venv first)
	pytest -q
	lint-imports
	mypy
	cd frontend && npm run typecheck && npm run profiles:check && npm test
