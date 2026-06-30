# VortexFlow developer tasks. Run `make` (or `make help`) for the list.
#
# Daily loop:  make dev-backend   (API on :8001, --reload)
#              make dev-frontend  (SPA on :5173)
#              make dev-seed      (login: admin@vortexflow.dev / devpassword)
# Before committing:  make fmt    (so the pre-commit ruff-format hook doesn't
#                                  reformat-and-abort your commit)
#
# Backend env lives in backend/.env.dev (git-ignored, auto-created from
# backend/.env.dev.example). See AGENTS.md.

BE := backend
FE := frontend
PY := .venv/bin
ENV := $(BE)/.env.dev
# Canonical Vector version — keep the deployed pins (docker-compose, agent image)
# and the generated catalog in sync with this. Bump here, then `make catalog`.
VECTOR_VERSION ?= 0.56.0
# Load the dev env inside a recipe that has already `cd`'d into backend/.
LOAD := set -a && . ./.env.dev && set +a

.DEFAULT_GOAL := help

# ── env bootstrap ────────────────────────────────────────────────────────────
$(ENV): $(BE)/.env.dev.example
	@cp $(BE)/.env.dev.example $(ENV)
	@echo "→ created $(ENV) from example (edit if your dev DB differs)"

.PHONY: dev-env
dev-env: $(ENV) ## Create backend/.env.dev from the example if missing

# ── run ──────────────────────────────────────────────────────────────────────
.PHONY: dev-backend
dev-backend: $(ENV) ## Run the dev API (uvicorn :8001, auto-reload)
	cd $(BE) && $(LOAD) && $(PY)/uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

.PHONY: dev-frontend
dev-frontend: ## Run the dev SPA (vite :5173, proxies /api → :8001)
	cd $(FE) && pnpm dev

.PHONY: dev-seed
dev-seed: $(ENV) ## Seed a known dev admin (admin@vortexflow.dev / devpassword)
	cd $(BE) && $(LOAD) && PYTHONPATH=. $(PY)/python scripts/dev_seed.py

# ── quality ──────────────────────────────────────────────────────────────────
.PHONY: fmt
fmt: ## Auto-format + autofix the backend (run BEFORE staging to avoid the hook dance)
	cd $(BE) && $(PY)/ruff format app scripts && $(PY)/ruff check --fix app scripts

.PHONY: catalog
catalog: ## Regenerate the source/sink catalog from Vector's schema (VECTOR_VERSION=x.y.z)
	docker run --rm timberio/vector:$(VECTOR_VERSION)-alpine generate-schema \
		> $(FE)/schema/vector-$(VECTOR_VERSION)-schema.json
	cd $(FE) && VECTOR_SCHEMA_VERSION=$(VECTOR_VERSION) pnpm gen:catalog
	@echo "→ catalog regenerated from Vector $(VECTOR_VERSION). Keep the deployed Vector pins in sync."

.PHONY: lint
lint: ## Lint everything (ruff check + format-check + frontend typecheck)
	cd $(BE) && $(PY)/ruff check app && $(PY)/ruff format --check app
	cd $(FE) && pnpm tsc --noEmit

.PHONY: test
test: $(ENV) ## Run backend unit tests (pytest)
	cd $(BE) && $(LOAD) && PYTHONPATH=. $(PY)/pytest -q

# ── contract drift sentinel ──────────────────────────────────────────────────
# Build-time drift guard (catalog ⟷ allowlist ⟷ schema).
# Runs offline from the repo root; the app is importable via PYTHONPATH.
SENTINEL := PYTHONPATH=$(BE):. $(BE)/$(PY)/python -m contracts.sentinel

.PHONY: sentinel
sentinel: ## Run the Contract Drift Sentinel (offline drift checks; exits 1 on drift)
	$(SENTINEL) check

.PHONY: sentinel-online
sentinel-online: ## Sentinel incl. docker/network checks (A2 schema vs binary, A3 version)
	$(SENTINEL) check --online

.PHONY: sentinel-test
sentinel-test: ## Run the Sentinel's drift-injection test suite
	PYTHONPATH=$(BE):. $(BE)/$(PY)/pytest contracts/tests -q

.PHONY: sentinel-baseline
sentinel-baseline: ## Snapshot model columns for the C2 schema-drift check (run at release)
	$(SENTINEL) baseline

# ── agent ────────────────────────────────────────────────────────────────────
# Cross-compile the Go agent. Uses local `go` if present, else the golang:1.26
# docker image (matches the backend image build + go.mod's 1.26.4 requirement).
.PHONY: agent-build
agent-build: ## Build the agent for this host (local go, or docker golang fallback)
	@if command -v go >/dev/null 2>&1; then \
		cd $(BE)/../agent && go build -o bin/vortexflow-agent . && echo "→ agent/bin/vortexflow-agent"; \
	else \
		echo "go not found — building via docker golang:1.26"; \
		docker run --rm -v "$(PWD)/agent":/src -w /src -e CGO_ENABLED=0 \
			golang:1.26 go build -o /src/bin/vortexflow-agent . && echo "→ agent/bin/vortexflow-agent"; \
	fi

# ── security / release helpers ───────────────────────────────────────────────
.PHONY: secret-scan
secret-scan: ## Scan full git history for secrets (gitleaks via docker)
	docker run --rm -v "$(PWD)":/repo ghcr.io/gitleaks/gitleaks:latest \
		git /repo --config /repo/.gitleaks.toml

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
