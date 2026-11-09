# Security controls (demo scope)

This is a demonstration system with synthetic data. The controls below are reasonable
engineering practice for a demo; they are **not** a claim of compliance with any banking
regulation, PCI DSS, or production security standard, and the system has not been
independently assessed.

## Implemented

| Area | Control | Where |
| --- | --- | --- |
| Passwords | Argon2id via `argon2-cffi`; timing equalised for unknown users | `app/security.py` |
| Credentials | No default passwords; seed reads `NVB_SEED_*_PASSWORD` or generates random ones into a 0600 file; never printed, never on the login page | `app/services/seed.py`, `app/cli.py` |
| Sessions | Random 256-bit token, only SHA-256 stored; HttpOnly + Secure + SameSite=Lax cookie; idle and absolute expiry; server-side logout | `app/security.py`, `app/api/auth.py` |
| CSRF | Per-session synchroniser token in `X-CSRF-Token` on every POST/PATCH | `app/deps.py` |
| Login abuse | Failure counters per hashed username and per hashed IP in PostgreSQL (shared by all replicas); identical responses for unknown users | `app/security.py` |
| Authorization | Roles `customer`, `admin`, `demo` checked server-side on every protected route; ownership filters on every customer query; foreign resources → 404 | `app/deps.py`, `app/api/*` |
| Input validation | Pydantic models with bounds, `extra="forbid"` where relevant, decimal-string money parsing, LIKE-wildcard escaping, CSV formula-injection neutralisation | `app/api/*`, `app/money.py` |
| SQL | SQLAlchemy expressions / bound parameters only; no string-built SQL from user input | all |
| Money integrity | Integer minor units, row locks, conditional debit, DB `CHECK` constraints, idempotency keys | `app/services/transfers.py`, `app/models.py` |
| CORS | Off by default (same-origin SPA). Explicit allow-list via `NVB_CORS_ORIGINS` only if needed | `app/main.py` |
| Headers | CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS when secure cookies are on, `Cache-Control: no-store` on API | `app/main.py` |
| Metrics / admin | `/metrics` needs a bearer token; nginx denies it externally on the VM; NetworkPolicy limits it to the monitoring namespace on OpenShift; ops APIs require the admin role; interactive API docs disabled | `app/api/health.py`, `deploy/` |
| Demo workload | Disabled by default; route not registered unless enabled; demo role only; bounded inputs, concurrency and execution time | `app/api/demo.py`, `app/services/workload.py` |
| Sign-up | Server-side username/password/profile rules (password ≥ 10 chars, letter + digit, not containing the username), DB-backed per-IP rate limit, can be disabled (`NVB_SELF_REGISTRATION_ENABLED`) | `app/validation.py`, `app/api/auth.py` |
| Password reset | Identical response whether or not the user exists; silent per-user/per-IP throttle; random single-use tokens, only SHA-256 stored, short expiry, older tokens invalidated, all sessions ended and lockout cleared on reset | `app/services/onboarding.py`, `app/api/auth.py` |
| Cash operations | Same guarantees as transfers: integer minor units, row lock, conditional debit, CHECK constraint, idempotency keys, per-operation limits, ownership checks | `app/services/cash.py`, `app/api/cash.py` |
| Audit | `audit_events` for login success/failure/throttle, logout, transfers (completed/failed/rejected), CSV export, profile changes (field names only), admin unlock, seed and reset | `app/audit.py` |
| Logging | JSON logs with request IDs; no passwords, tokens, cookies or full account numbers; sensitive keys redacted defensively | `app/logging_config.py` |
| Containers | Non-root, arbitrary UID, read-only root FS, drop ALL capabilities, no privilege escalation, seccomp RuntimeDefault, no SA token mounted, no RBAC needed | `Containerfile`, `deploy/openshift/base/` |
| VM | Dedicated `nvb` user, systemd hardening, PostgreSQL roles with least privilege (`nvb_app` DML only), firewall 80/443 only | `deploy/vm/` |

## Scanning (run before every demo build)

```bash
# Python dependencies
pip install pip-audit && pip-audit -r backend/requirements.txt
# Node dependencies
cd frontend && npm audit --omit=dev
# Image (any one of these)
trivy image <registry>/nvb-app:<tag>
grype <registry>/nvb-app:<tag>
# or Red Hat Advanced Cluster Security: roxctl image scan --image <registry>/nvb-app:<tag>
# Secrets in the repo
gitleaks detect --source .
```

Pinned versions were current at the time of writing; re-check them — the tools above will
report known CVEs. Upgrade, re-run the test suite, rebuild.

## Known limitations (acceptable for a demo, not for production)

* The **demo mailbox** lets the admin read password-reset and account-setup links, so an admin
  can take over any account. It stands in for an email provider and must never exist in a real system.
* No MFA, no password reset, no account lockout notifications.
* Login throttling is counter-based in PostgreSQL — fine for a demo, not a WAF.
* No field-level encryption; PostgreSQL TLS is `prefer` by default on the VM — set
  `NVB_DB_SSLMODE=verify-full` with a proper CA when the DB is reached over a network.
* Audit events are stored in the same database the app writes to (not tamper-evident).
* `FORWARDED_ALLOW_IPS=*` in the image relies on NetworkPolicy so only the router reaches
  pods; narrow it if your network differs.
