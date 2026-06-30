# Contributing to VortexFlow

Thanks for your interest in VortexFlow — the open-source control plane for your
[Vector](https://vector.dev) fleet. This guide covers how to set up a dev
environment, the standards we hold code to, and how to get a change merged.

By contributing you agree your contributions are licensed under the project's
[MPL 2.0](LICENSE) license.

## Ways to contribute

- **Report a bug** — open an issue with the bug template.
- **Request a feature** — open an issue with the feature template; for larger
  ideas, start a discussion first so we can agree on direction.
- **Send a pull request** — fixes, features, docs. For anything non-trivial,
  open an issue first so we don't both build the same thing.
- **Security issues** — do **not** open a public issue. See [SECURITY.md](SECURITY.md).

## Project layout

```
backend/    FastAPI (Python 3.12) — API, render/deploy engine, auth
frontend/   React + Vite + TypeScript — the UI
agent/      vortexflow-agent — a single static Go binary (pull-based config sync)
docker/     Docker Compose + Dockerfiles + nginx
docs/guide/ user & operator documentation
```

## Dev environment

You need Docker + Compose, Node 22+ with `pnpm`, and Python 3.12.

**Full stack (closest to production):**

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d
# open https://localhost — demo login: admin@example.com / ChangeMe123!
```

**Local dev loop (recommended) — via the Makefile:**

```bash
make dev-backend    # API on :8001 (--reload)
make dev-frontend   # SPA on :5173 (proxies /api → :8001)
make dev-seed       # login: admin@vortexflow.dev / devpassword
```

Run `make` for the full target list. After your first checkout, create the backend
virtualenv (`cd backend && python -m venv .venv && source .venv/bin/activate &&
pip install -r requirements.txt`) and install frontend deps (`cd frontend && pnpm
install`); `make` handles the rest, including `backend/.env.dev`.

**Before you commit:** run `make fmt` (so the `ruff-format` pre-commit hook doesn't
reformat-and-abort your commit). `make lint` runs the full check set.

**Agent (Go):** `make agent-build` (uses local `go`, or docker `golang:1.26`).

See **[`AGENTS.md`](AGENTS.md)** for the full dev-tooling guide (env file,
conventions, and patterns), and `make help` for the make-target reference.

## Standards

These are enforced by pre-commit hooks and CI — run them locally before pushing.

**Backend (Python):**
- `ruff check` + `ruff format` — lint & format.
- `mypy` — type checking. No untyped code.
- All API inputs validated with Pydantic.

**Frontend (TypeScript):**
- ESLint + Prettier.
- Strict TypeScript — **no `any`**.
- Validate inputs with Zod; theme via the design tokens, not hard-coded colors.

**Tests:** add or update tests for behavior changes (`backend/tests/`). Keep the
existing suites green.

**Set up the hooks once:**

```bash
pip install pre-commit && pre-commit install
```

## Pull request process

1. Fork and branch from `main` (`fix/...`, `feat/...`).
2. Keep PRs focused — one logical change. Update docs (`docs/guide/`) and
   `CHANGELOG.md` (the `Unreleased` section) when behavior changes.
3. Ensure lint, types, and tests pass locally.
4. Open the PR using the template; describe the change and how you verified it.
5. A maintainer reviews; security-sensitive surfaces (auth, secrets, config I/O,
   the agent, subprocess calls) get extra scrutiny.

## Commit messages

Imperative mood, concise subject, body explaining the *why* when it isn't
obvious. Reference issues (`Fixes #123`).

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By
participating you agree to uphold it.
