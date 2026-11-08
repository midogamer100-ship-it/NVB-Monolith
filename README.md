# Nova Valley Bank (NVB) — modernization demo

> **Demo environment — synthetic data.** NVB is a fictitious bank. There are no real
> customers, no real banking integrations and no real financial transactions. This
> project is **not** production-ready and does **not** claim to meet any banking
> regulatory or compliance requirement.

One codebase that runs unchanged on:

1. a single Linux VM on VMware (app + PostgreSQL),
2. the same VM after migration to **OpenShift Virtualization** (migration is done with
   external tooling such as the Migration Toolkit for Virtualization — *not* by this app),
3. **OpenShift containers** (Deployment + HPA) while PostgreSQL stays on the migrated VM.

Migrating a VM does **not** by itself add horizontal scaling. Scaling comes from step 3,
and only helps when the measured bottleneck is application CPU — see
[docs/SCALING_DEMO.md](docs/SCALING_DEMO.md).

## Architecture summary

```
Browser ──HTTPS──► reverse proxy / OpenShift Route
                     │
                     ▼
            NVB app (FastAPI + uvicorn, port 8080)       ← one artifact: API + built React SPA
            • /api/*        JSON API, DB-backed sessions, CSRF, RBAC
            • /health/live  process only        /health/ready  DB check (short timeout)
            • /metrics      Prometheus (bearer token)
                     │ SQLAlchemy (psycopg 3), pooled
                     ▼
            PostgreSQL 16 (on the VM in every phase)
```

* **Frontend:** React 18 + TypeScript + Tailwind, built by Vite into static files that the
  backend serves — one deployable artifact.
* **Backend:** FastAPI, SQLAlchemy 2, Alembic, argon2 password hashing, Prometheus client.
* **State:** everything (sessions, login-throttle counters, idempotency keys, ledger) lives
  in PostgreSQL, so any replica can serve any request. Nothing is kept on local disk.
* **Money:** integer piastres (`BIGINT`), never floats. Transfers lock both account rows in
  id order, debit conditionally (`balance >= amount`), and write transfer + two ledger
  entries in one transaction. A `CHECK (balance_minor >= 0)` constraint backs it up.
* **Idempotency:** `Idempotency-Key` header required; unique per user in the DB.

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository layout

```
backend/                 FastAPI app, Alembic migrations, tests
  app/api/               routers: auth, accounts, transactions, transfers, dashboard,
                         profile, ops (admin), demo (synthetic workload), health
  app/services/          transfers, seed, synthetic workload, Prometheus integration
  app/cli.py             migrate | seed | reset-demo-data | check-db
  alembic/               migrations (explicit, single operation)
  tests/                 pytest suite (SQLite by default, PostgreSQL optional)
frontend/                React + TypeScript + Tailwind SPA (Vite)
Containerfile            multi-stage UBI 9 image, non-root, arbitrary UID, port 8080
.dockerignore
compose.yaml             local app + PostgreSQL 16
deploy/compose/          Compose helpers (least-privilege DB role, env example)
deploy/vm/               systemd unit, nginx TLS proxy, PostgreSQL setup, backup/restore
deploy/openshift/        Kustomize base + overlays, jobs (migrate/seed), optional monitoring
loadtest/k6/             six k6 scenarios + shared library
loadtest/results-template.md
docs/                    architecture, VM & OpenShift guides, scaling demo, load testing,
                         demo walkthrough, troubleshooting, security
.env.example             every configuration variable, documented
```

## Quick start (local, without containers)

Requirements: Python 3.12, Node.js ≥ 20.19, PostgreSQL 16 (or use Compose below).

```bash
# 1. Backend dependencies
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

# 2. Frontend build (served by the backend)
cd ../frontend && npm ci && npm run build && cd ../backend
export NVB_STATIC_DIR="$(pwd)/../frontend/dist"

# 3. Configure (local plain-http only)
export NVB_DB_HOST=127.0.0.1 NVB_DB_USER=nvb_app NVB_DB_PASSWORD='<your local password>'
export NVB_DB_MIGRATION_USER=nvb_owner NVB_DB_MIGRATION_PASSWORD='<your local owner password>'
export NVB_COOKIE_SECURE=false NVB_ENVIRONMENT_LABEL="Local" NVB_METRICS_TOKEN="$(openssl rand -hex 24)"

# 4. Schema + deterministic synthetic data (explicit, one-time operations)
python -m app.cli migrate
python -m app.cli seed --credentials-file ./nvb-demo-credentials.txt   # 0600, git-ignored

# 5. Run
uvicorn --factory app.main:app_factory --host 127.0.0.1 --port 8080
```

Open http://127.0.0.1:8080. Demo usernames are `customer001`…`customer060`,
`loadtest001`…`loadtest100`, `demoload01`…`demoload10` (demo role) and `opsadmin` (admin).
Passwords are whatever you set in `NVB_SEED_*_PASSWORD`, or the randomly generated ones in
the credentials file. **The login page never shows passwords.**

For frontend development with hot reload: `cd frontend && npm run dev` (proxies `/api` to
port 8080).

## Quick start (Compose)

```bash
cp deploy/compose/env.compose.example .env      # set your own local passwords
docker compose up -d --build                     # or: podman compose up -d --build
docker compose run --rm app sh -c 'python -m app.cli seed --credentials-file /tmp/c.txt && cat /tmp/c.txt'
```

Then open http://localhost:8080. Compose runs `migrate` once before `app` starts.

## Tests

```bash
cd backend
pytest                                         # SQLite, no external services
NVB_TEST_DATABASE_URL=postgresql+psycopg://nvb_test:<pw>@127.0.0.1:5432/nvb_test pytest
```

The PostgreSQL run is strongly recommended before a demo: `SELECT … FOR UPDATE` row locking
is only truly exercised on PostgreSQL. **The test database is wiped** — use a dedicated one.

Coverage: authentication and sessions (expiry, logout, CSRF, generic errors, throttling
shared across instances), role enforcement, cross-customer isolation (accounts,
transactions, CSV export, beneficiaries, debits), transfer atomicity (fault injected
between debit and credit), insufficient funds, concurrent transfers, idempotent retries
(sequential, concurrent, and across instances), session continuity across two app
instances, health endpoints, metrics protection and label cardinality, migrations ↔ models
consistency, deterministic seed, and synthetic-workload guards.

## Guarded demo-data reset

```bash
NVB_ALLOW_DEMO_RESET=true python -m app.cli reset-demo-data --confirm "RESET NVB DEMO DATA"
```

Both the environment flag and the exact phrase are required. It truncates every NVB table
and re-seeds. The action is written to the audit log.

## Documentation

| Topic | File |
| --- | --- |
| Architecture, design decisions, assumptions | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| VM install (RHEL 9-compatible) | [docs/VM_DEPLOYMENT.md](docs/VM_DEPLOYMENT.md) |
| OpenShift deployment, pool sizing, image scanning | [docs/OPENSHIFT_DEPLOYMENT.md](docs/OPENSHIFT_DEPLOYMENT.md) |
| Repeatable scaling demonstration | [docs/SCALING_DEMO.md](docs/SCALING_DEMO.md) |
| k6 load tests | [docs/LOAD_TESTING.md](docs/LOAD_TESTING.md), [loadtest/results-template.md](loadtest/results-template.md) |
| Live demo walkthrough | [docs/DEMO_WALKTHROUGH.md](docs/DEMO_WALKTHROUGH.md) |
| Troubleshooting | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Security controls and limits | [docs/SECURITY.md](docs/SECURITY.md) |

## Verification status of this delivery

| Item | Status |
| --- | --- |
| Backend test suite (pytest, SQLite) | Run locally — all tests pass |
| Backend tests against PostgreSQL | **Not run** (no PostgreSQL available in the build environment) |
| Frontend type-check and production build | Run locally — passes |
| End-to-end smoke test (CLI migrate → seed → reset, uvicorn, browser: login, dashboard, transfer → receipt, transactions, operations, demo workload) | Run locally against SQLite |
| Container image build, Compose stack | **Not run** (no container runtime available) |
| OpenShift manifests | YAML parsed and kustomize references checked; **not** applied to a cluster |
| k6 scripts | Syntax-checked with `node --check`; **not** executed (k6 not installed) |
| VM guide on RHEL / VMware / OpenShift Virtualization | **Not tested**; requires access to those environments |

No benchmark numbers are included anywhere. Record your own measurements in
[loadtest/results-template.md](loadtest/results-template.md).
