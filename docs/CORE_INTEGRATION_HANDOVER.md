# Core integration (`/internal/v1`) — handover to infra

Status: **code only. Disabled by default. Not deployed anywhere.** No live rollout has been
performed, and nothing in this branch changes OpenShift, the VMs, nginx, golden images,
databases or secrets.

## Identification

| Item | Value |
| --- | --- |
| Branch | `feature/digital-services-core-integration` |
| Based on | `main` at `c2b8006a7a599881610c442e937080978e6a896c` (verified on the remote before branching) |
| Commits | `6545f08` API + authentication (patch 0001), `5656c40` statement-v2 dataset (patch 0002), then this handover document. The final commit is the head of the branch / the draft PR. |
| Digital-services compatibility target | `nvb-digital-services-handover` at `c4e2dbb118ef94ffd7bb42ef90000cf7ee9f910e` |
| Source of the code | `core-patch/0001-*.patch` and `core-patch/0002-*.patch` from that commit, originally authored against Core `ffd32015aa00564054bb177f6580196ce1b1355c` |

Both patches applied to current `main` with `git am -3` **without conflicts and without
modification**. Between the patch base and current `main` only rebrand text changed in the
backend (`main.py`, `serializers.py`, `services/onboarding.py`, `services/seed.py`), none of it
in the lines the patches touch.

## Changed files

| File | Change | Why |
| --- | --- | --- |
| `backend/app/api/integration.py` | new | `/internal/v1` router, client registry (hashed tokens, scopes), bounded export slots |
| `backend/app/services/integration_exports.py` | new | read-only queries: subject, accounts, statement manifest + content digest, entries, discovery |
| `backend/app/config.py` | +19 lines | `integration_*` settings, all defaulting to off / safe values |
| `backend/app/main.py` | +6 lines | router imported and registered **only** when `NVB_INTEGRATION_ENABLED=true` |
| `backend/tests/integration_support.py` | new | test helpers |
| `backend/tests/test_integration_auth.py` | new | 25 tests: credentials, scopes, fail-closed, disabled-by-default, introspection |
| `backend/tests/test_integration_exports.py` | new | 23 tests: payloads, pagination, period rules, audit, capacity |
| `backend/tests/test_integration_consistency.py` | new | 13 tests (3 PostgreSQL-only): digest/dataset-id consistency checks |
| `backend/tests/test_health.py` | ±5 lines | test-only: the "no account id in metrics" assertion now inspects label values only (a float sample could contain `999999`) |
| `docs/CORE_INTEGRATION_HANDOVER.md` | new | this document |

Not changed: Alembic migrations, `models.py`, `db.py`, `requirements.txt`, the Containerfile,
any existing route, money movement, balances, transfer/cash logic, sessions, CSRF.
`git diff --stat c2b8006 -- backend/alembic backend/app/models.py backend/app/db.py backend/requirements.txt`
is empty. **No schema migration is required.** The only database writes made by the integration
are audit rows (manifest/discovery calls) and the existing session bookkeeping of
`load_session` during introspection — not financial mutations.

## Endpoints and scopes

Full contract: `contracts/core-integration-v1.md` in the digital-services release.

| Endpoint | Scope |
| --- | --- |
| `POST /internal/v1/sessions/introspect` | `identity:introspect` (+ `accounts:read` for `include_accounts`) |
| `GET /internal/v1/subjects/{subject}/accounts` | `accounts:read` |
| `GET /internal/v1/accounts/{id}/statement-manifest` | `statements:extract` or `summaries:read` |
| `GET /internal/v1/accounts/{id}/statement-entries` | `statements:extract` |
| `GET /internal/v1/discovery/statement-accounts` | `accounts:discover` |

Errors use `{"error": {"code", "message"}}`; missing/invalid credentials → 401, missing scope → 403,
foreign or unknown account/subject → 404 (no existence leak), export capacity → 429 + `Retry-After`.

## Environment variables (prefix `NVB_`)

| Variable | Default | Notes |
| --- | --- | --- |
| `NVB_INTEGRATION_ENABLED` | `false` | Read at start. `false` ⇒ the router is never imported or registered |
| `NVB_INTEGRATION_CLIENTS_FILE` | unset | Required when enabled; missing / unreadable / malformed / unknown scope ⇒ every call 401 |
| `NVB_INTEGRATION_MAX_CONCURRENT_EXPORTS` | `2` | Per process |
| `NVB_INTEGRATION_EXPORT_QUEUE_TIMEOUT_SECONDS` | `2` | |
| `NVB_INTEGRATION_MAX_PAGE_SIZE` | `1000` | Upper bound of `limit` for entries |
| `NVB_INTEGRATION_MAX_PERIOD_DAYS` | `400` | |
| `NVB_INTEGRATION_SETTLE_SECONDS` | `300` | Period must have ended at least this long ago |
| `NVB_INTEGRATION_DISCOVERY_MAX_PAGE_SIZE` | `500` | |
| `NVB_INTEGRATION_MAX_STATEMENT_ENTRIES` | `250000` | Above it `422 dataset_too_large` (never truncated) |

## Credential file schema (placeholders only — never commit real values)

```json
{"clients": [
  {"client_id": "nvb-core-adapter",
   "token_sha256": ["<sha256 hex of current token>", "<sha256 hex of next token during rotation>"],
   "scopes": ["identity:introspect", "accounts:read", "statements:extract", "summaries:read", "accounts:discover"]}
]}
```

Only SHA-256 digests are stored. Mount it from a Secret, readable by the core user only. The file
is re-read when it changes (checked at most every 15 s), so token rotation needs no restart.

## Container compatibility

The root `Containerfile` copies the whole `backend/app` tree, so both new modules are included
with no Containerfile change (`backend/tests` stays excluded by `.dockerignore`). It was compared
with the release's `deploy/openshift/overlays/test/core-test.yaml` and
`core-test-jobs/jobs.yaml`: port 8080, `WORKDIR /opt/nvb/backend`, `python -m app.cli migrate`
and `python -m app.cli seed --credentials-file /tmp/...` all match. The manifest's
`UVICORN_SSL_CERTFILE` / `UVICORN_SSL_KEYFILE` work with the existing `uvicorn` command because
uvicorn 0.34.2 reads `UVICORN_*` environment variables. No incompatibility found.
**The image has not been built in this handover**; infra builds it on OpenShift.

## Activation (infra, through the normal deployment process)

1. Deploy this revision with the flag still `false` — behaviour is identical to `main`.
2. Provide the credential file from a Secret and set `NVB_INTEGRATION_CLIENTS_FILE`.
3. Set `NVB_INTEGRATION_ENABLED=true` and restart the core.
4. Verify from the adapter side with its token.

Deactivation: set `NVB_INTEGRATION_ENABLED=false` and restart; the routes disappear. Nothing to
clean up and no migration to reverse.

## Network exposure — action for infra

The VM nginx config (`deploy/vm/nginx-nvb.conf`) forwards every path except `/metrics`, so once
the flag is enabled `/internal/v1` is reachable through the existing Core route. Every request is
still authenticated, but **authentication alone is not network isolation**: infra must review
reachability and restrict `/internal/` to the intended callers (e.g. the adapter's egress
address at nginx/HAProxy). This branch does not change the live nginx.

## Tests run for this handover

Run once on SQLite through the release's guarded runner (`scripts/safe_core_tests.py`, which
strips inherited `NVB_*`/`PG*` variables), against this branch:

* `test_integration_auth.py`, `test_integration_exports.py`, `test_integration_consistency.py`
  (all supplied integration tests), `test_health.py` (modified by the patch), `test_auth.py`
  (login/session/CSRF), `test_accounts_isolation.py` (ownership), and two financial regressions
  from `test_transfers.py` (successful transfer + ledger; concurrent transfers never overdraw).
* Result: **93 collected — 90 passed, 3 skipped, 0 failed.** The 3 skipped tests need PostgreSQL.
* `git diff --check` clean.

Not run: the 3 PostgreSQL-only consistency tests (no disposable PostgreSQL was available — SQLite
does not prove PostgreSQL snapshot/locking semantics), the rest of the Core suite, a container
build, any digital-services or load test. Infra should run the full suite against a disposable
PostgreSQL with the guarded runner before rollout.
