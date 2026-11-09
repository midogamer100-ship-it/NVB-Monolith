# Sign-up, admin-created users, password reset, deposit & withdraw

> Demo environment — synthetic data. No real email or SMS is ever sent: "emails" go to a
> **demo mailbox** that only the admin can read. Deposits and withdrawals are simulated
> branch cash operations — no real money moves.

The public API below is **identical in the monolith and microservices editions**, so the
same React frontend works with both.

## 1. Self sign-up — `POST /api/auth/register` (public)

Disabled with `NVB_SELF_REGISTRATION_ENABLED=false` (route then returns 404).

Request:
```json
{"username": "nour.k", "password": "...", "full_name": "Nour Kamal",
 "email": "nour@example.test", "phone": "+201012345678", "city": "Cairo"}
```

Validation (server-side, 422 with FastAPI's standard error list on failure):

| Field | Rule |
| --- | --- |
| username | lower-cased; `^[a-z][a-z0-9_.-]{3,31}$` |
| password | 10–128 chars, at least one letter and one digit, must not contain the username |
| full_name | 3–120 chars, letters, spaces, `'` and `-` |
| email, phone, city | same rules as the profile page (`+20` mobile, city from the fixed list) |

Responses:
* `201` → `{"username", "customer_number", "account": {"masked_number", "type": "current", "nickname", "balance": "0.00"}, "message": "Your account is ready. Please sign in."}`
  (no automatic sign-in)
* `409` → `{"detail": {"code": "username_taken", "message": "That username is not available."}}`
* `429` → `{"detail": "Too many sign-up attempts. Please try again later."}` — at most
  `NVB_REGISTRATION_MAX_PER_IP_PER_HOUR` (default 10) per client IP, counted in the database
  so the limit holds across replicas.

Effects: one `customer` user (Argon2 hash), one customer profile
(`customer_number = "C" + 6-digit customer id`), one active EGP **current** account named
"Everyday Current" with balance 0 and a fresh unique account number. Audit event
`auth.register` (outcome success / duplicate / throttled), never containing the password.

## 2. Admin creates a user — `POST /api/ops/users` (admin, CSRF)

Request: `{"username", "full_name", "email", "phone", "city"}` (same rules as sign-up; no
password). Role is always `customer`.

`201` → `{"username", "customer_number", "account": {...as above}, "message": "User created. A set-password link was sent to the demo mailbox."}`;
`409` username taken; `422` validation.

The new user gets an unusable random password and an **account-setup** link (kind
`account_setup`, valid `NVB_ACCOUNT_SETUP_TTL_HOURS`, default 24) delivered to the demo
mailbox. The link is consumed by the same reset endpoint (§4). Audit `admin.create_user`.

## 3. Forgot password — `POST /api/auth/password/forgot` (public)

Request `{"username": "..."}`. **Always** `202`
`{"message": "If that account exists, we've sent password reset instructions to its registered email."}`
— the response never reveals whether the username exists.

If the user exists and is active (any role): previous unused tokens of that user are
invalidated, a new single-use token (`secrets.token_urlsafe(32)`, only its SHA-256 stored,
valid `NVB_PASSWORD_RESET_TTL_MINUTES`, default 15) is created, and a message is put in the
demo mailbox: subject "Reset your Nova Valley Bank password", body with the link
`/reset-password?token=<token>`. Throttle (silent, still 202): 3 requests per username and
20 per IP per 15 minutes. Audit `auth.password_reset_requested` (issued / ignored / throttled).

## 4. Reset or set password — `POST /api/auth/password/reset` (public)

Request `{"token": "...", "new_password": "..."}` (password rules as §1, checked against the
token owner's username).

* `200` → `{"message": "Your password has been updated. Please sign in."}`
* `400` → `{"detail": {"code": "invalid_or_expired_token", "message": "This link is invalid or has expired. Request a new one."}}`
* `422` password policy.

Effects: new Argon2 hash, token marked used (single use), **all of the user's sessions are
deleted**, failed-login counters cleared. Audit `auth.password_reset` (success / failure).

## 5. Demo mailbox — `GET /api/ops/mailbox?limit=50` (admin)

`{"items": [{"id", "to", "username", "subject", "body", "kind", "created_at"}], "demo_only": true}`,
newest first. `to` is the customer's registered email (or `<username>@nvb-demo.invalid` for
admin/demo users). This page stands in for a real email provider; it exists only because the
demo has no mail integration.

## 6. Deposit and withdraw

`POST /api/accounts/{account_id}/deposit` and `POST /api/accounts/{account_id}/withdraw`
(customer, CSRF, header `Idempotency-Key` required — same rule as transfers).

Request: `{"amount": "500.00", "description": "optional, ≤ 140 chars, same charset as transfers"}`

| | Deposit | Withdraw |
| --- | --- | --- |
| Per-operation limit | `NVB_MAX_DEPOSIT_MINOR` (default 10,000,000 = 100,000.00 EGP) | `NVB_MAX_WITHDRAWAL_MINOR` (default 5,000,000 = 50,000.00 EGP) |
| Ledger entry | credit, type `deposit`, category `Cash deposit`, default description "Cash deposit" | debit, type `withdrawal`, category `Cash`, default description "Cash withdrawal" |
| Counterparty | `NVB Branch (demo)` | `NVB Branch (demo)` |

Responses:
* `201` → `{"reference", "kind": "deposit"|"withdrawal", "status": "completed", "amount", "amount_minor", "description", "account": {"id", "masked_number", "nickname", "balance", "balance_minor"}, "created_at"}`
* `200` + header `Idempotent-Replayed: true` → retry with same key and same payload (original result)
* `409` → same key, different payload
* `422` → invalid amount / over limit / inactive account; withdrawal with insufficient funds
  returns `422` with the body above but `"status": "failed"`, `"failure_reason": "insufficient_funds"`,
  `"message": "Insufficient funds. No money was moved."` — persisted and replayable
* `404` → account not owned by the caller (no existence leak)

Correctness: row lock (`SELECT … FOR UPDATE`), conditional debit (`balance >= amount`),
`CHECK balance >= 0`, operation record + ledger entry in one transaction, unique
`(user_id, idempotency_key)` in table `cash_operations`. Metric
`nvb_cash_operations_total{kind, outcome}`. Audit `account.deposit` / `account.withdraw`.
`withdrawal` is added to the transaction-type filter.

## Microservices edition — who does what

| Feature | Service(s) |
| --- | --- |
| register | gateway (public route) → **auth** orchestrates: create inactive user → customer `POST /internal/customers` → accounts `POST /internal/accounts` → activate user. On any failure it compensates (customer `DELETE /internal/customers/{id}`, delete user) and returns `503 {"detail": {"code": "registration_unavailable", ...}}` |
| admin create user | ops `POST /api/ops/users` → auth `POST /internal/users` (same orchestration, no password, issues setup link) |
| forgot / reset password, mailbox storage | **auth** (`password_reset_tokens`, `outbox_messages` in schema `auth`); email looked up via customer summary (now includes `email`) |
| mailbox page | ops `GET /api/ops/mailbox` → auth `GET /internal/outbox` |
| deposit / withdraw | **accounts** (`cash_operations` in schema `ledger`) |

New internal calls (signed service identity, NetworkPolicies updated): auth → customer,
auth → accounts. Internal routes are idempotent per `user_id` / `customer_id` so a retried
orchestration step never creates duplicates.
