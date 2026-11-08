# Architecture and design decisions

## Components

| Component | Choice | Why |
| --- | --- | --- |
| UI | React 18 + TypeScript + Tailwind 3, Vite 6 | Static build served by the backend → one artifact |
| API | FastAPI 0.115 on uvicorn 0.34 (Python 3.12) | Simple, typed, good validation |
| Data access | SQLAlchemy 2.0 + psycopg 3, Alembic 1.16 | Parameterised SQL everywhere, versioned schema |
| Database | PostgreSQL 16 | Row locks, CHECK constraints, unique indexes |
| Passwords | argon2-cffi (Argon2id) | Maintained, memory-hard |
| Metrics | prometheus-client | `/metrics`, multiprocess mode for multi-worker VMs |
| Load | k6 | Scriptable, reproducible scenarios |

One application service, one database. No cache, queue or service mesh.

## Request path

1. `observe` middleware assigns/propagates `X-Request-ID`, records metrics by **route
   template** (`/api/accounts/{account_id}`, never the raw path), adds security headers and
   `X-NVB-Instance` (identifies the replica that served the request).
2. `get_auth` loads the session from `user_sessions` by SHA-256 of the cookie token, slides
   the idle expiry (at most one write per minute), enforces CSRF on unsafe methods.
3. `require_customer` / `require_admin` / `require_demo` enforce roles server-side.
4. Every customer query is filtered by `customer_id`. Another customer's resource returns
   **404**, not 403, so existence is not leaked.

## Sessions and multi-replica behaviour

* Cookie `nvb_session`: random 256-bit token, `HttpOnly`, `Secure` (configurable for local
  http), `SameSite=Lax`, `Path=/`. Only its SHA-256 is stored.
* Idle timeout 15 min, absolute 8 h (configurable). Logout deletes the row → the token is
  dead on every replica immediately.
* CSRF: per-session synchroniser token returned by `/api/auth/login` and `/api/auth/me`,
  sent as `X-CSRF-Token` on POST/PATCH, compared in constant time.
* Login throttling: failures counted in `login_attempts` (hashed username and hashed IP),
  so limits hold across replicas. Throttled and unknown usernames get the same responses.

## Transfers

```
validate (read-only, ownership + amount + destination)
BEGIN
  SELECT … FROM accounts WHERE id IN (src, dst) ORDER BY id FOR UPDATE   -- deadlock-free order
  INSERT transfers (…, idempotency_key)        -- UNIQUE(user, key) → concurrent dupes collide
  if balance < amount: status=failed, COMMIT   -- persisted, replayable, no money moved
  UPDATE accounts SET balance = balance - :amt WHERE id=:src AND balance >= :amt   -- rowcount must be 1
  UPDATE accounts SET balance = balance + :amt WHERE id=:dst
  INSERT ledger_entries (debit), (credit)      -- each with balance_after
COMMIT
```

* Retry with the same key and same payload → original result (`Idempotent-Replayed: true`).
* Same key, different payload → `409`.
* Any exception before COMMIT rolls back everything (tested by injecting a failure between
  debit and credit).

## Health, metrics, logs

* `/health/live` never touches the DB — a DB outage must not make OpenShift restart pods.
* `/health/ready` runs `SELECT 1` with a 2 s statement timeout and 3 s connect timeout.
* `/metrics` requires `Authorization: Bearer $NVB_METRICS_TOKEN`; with no token configured it
  returns 403 unless `NVB_METRICS_ALLOW_UNAUTHENTICATED=true`.
* Metrics: `nvb_http_requests_total{method,route,status_class}`,
  `nvb_http_request_duration_seconds` histogram, `nvb_http_errors_total`,
  `nvb_http_requests_in_flight`, `nvb_transfers_total{outcome}`, `nvb_logins_total{outcome}`,
  `nvb_db_pool_checked_out|size|overflow`, `nvb_demo_workload_*`.
* Logs: JSON lines on stdout with `request_id` and `instance`. Keys that look sensitive
  (`password`, `token`, `session`, `csrf`, `cookie`, `authorization`, `account_number`) are
  redacted by the formatter; the code never logs them in the first place.

## Operations page

Shows only configured or measured values:

* environment label (`NVB_ENVIRONMENT_LABEL`), version, serving instance id;
* DB connectivity and round-trip time, connection-pool usage;
* **this instance**: request rate, p95, 5xx rate over the last minute (in-process);
* **all instances / replicas**: only when the optional read-only Prometheus/Thanos
  integration is configured; otherwise "Not configured". The app never calls the
  Kubernetes API and needs no cluster permissions.

## Synthetic CPU workload

`POST /api/demo/statement-analysis` exists only when `NVB_DEMO_WORKLOAD_ENABLED=true` and
only for the `demo` role. Inputs are an enum profile, months 1–12 and a seed; the amount of
work is fixed server-side (`NVB_DEMO_WORKLOAD_SIMULATIONS`, hard cap 20 000). A per-process
semaphore limits concurrency; callers wait at most 10 s, then get 429. Each run is cut off
after 5 s of compute. It is pure-Python computation on a PRNG-generated statement — no
sleeps, no injected failures, no customer data.

## Assumptions

* Currency is EGP only; amounts cross the API as decimal strings (`"1250.50"`).
* "Internal transfers" are between NVB accounts only: own accounts, or saved beneficiaries
  (seeded). Adding beneficiaries in the UI is out of scope.
* The per-transfer limit is 500,000.00 EGP (`NVB_MAX_TRANSFER_MINOR`).
* Seed data is deterministic for a given anchor date (default: today, UTC, so dashboards
  always show recent months; pin with `NVB_SEED_ANCHOR_DATE`).
* Admin and demo users have no bank accounts and cannot call customer APIs.
* SQLite is supported **only** for the automated tests and local smoke runs; every real
  deployment uses PostgreSQL.
* On the VM, uvicorn runs `WEB_CONCURRENCY` worker processes (one per vCPU). In containers
  it runs one process per pod (CPU limit 1) and scales with replicas.
