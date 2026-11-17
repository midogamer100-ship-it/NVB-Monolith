# Operations Admin portal — handover (Core frontend)

Status: **code only, not deployed.** No VM, Golden image, OpenShift object, nginx, Secret or
database was changed. No merge and no tag.

## Branches

| Repo | Branch | Base |
| --- | --- | --- |
| NVB-Monolith (this repo) | `feature/ops-admin-portal` | `feature/unified-banking-ui` @ `98effa30b9842726e8e3abe3155302b2feb36c9d` |
| nvb-digital-services-handover | `feature/ops-admin-loan-review` | `feature/unified-bank-gateway` @ `bde29bb5cf02b0150287a1df83617df7a6b40a5` |

The two branches belong together: this UI calls the new Loans/Statements endpoints of the
digital branch. Role model, authorization and transition: `docs/OPS_ADMIN_ROLE_MODEL.md` in the
digital-services branch.

## What changed here (frontend only)

* Admin (Core role `admin`) lands on `/admin` and gets an admin-only sidebar: **Admin overview,
  Loan management, Statement operations, Customer support, Profile, Sign out.**
* `/admin` — real loan counts (by status, pending review, pending decision, held by a retired
  reviewer) and statement status counts, each linking to its queue. Unavailable metrics show
  "Unavailable", never an estimate.
* `/admin/loans`, `/admin/loans/:id` — queue tabs, status filter, search; application detail with
  masked account context, synthetic background summary, Start/Take-over review, recommendation,
  final decision (reason ≥ 10 chars), history, stale-version (409) handling, own-application block,
  and a banner that approval disburses no money and creates no Core loan.
* `/admin/statements` — status/purpose counts, recent failures (error codes only), request list
  without download links, read-only batches; Resume/Retry-failed only for `batch_operations`.
* `/admin/customers` — the existing, already-authorized business tools moved from the old
  Operations page: create customer user, clear sign-in lockout, demo mailbox, audit events.
* `/admin/profile` — read-only session details and plain-language permissions.
* Removed from the UI: the technical Operations page (environment label, version/instance, server
  time, database host/latency/pool, per-instance stats, cluster/replica panels) and the separate
  reviewer workspace (`/loan-review`). `/operations` and `/loan-review` redirect to `/admin` for
  admins and to the customer home otherwise.
* Permission resolution: the admin pages read `capabilities` from Loans `/me` and Statements `/me`
  (server-side, from trusted Core introspection + explicit role assignment). A neutral loader shows
  while resolving (no flash of customer pages); "Access not granted" if the role is not assigned;
  a retry screen if a service is unavailable; 401 uses the existing session-expired redirect.
  Non-JSON error bodies (e.g. a proxy HTML page) are never rendered.

Not changed: Core backend APIs and authorization (admin endpoints were already `require_admin`,
customer endpoints `require_customer`), `/api/ops/status` and `/metrics` (still protected, still
available to infrastructure), the integration API, money movement, sessions/CSRF, Containerfile,
dependencies, migrations.

## Required configuration — NOT EXECUTED

The admin pages need the Core admin's subject to hold `operations_admin` in **both** the Loans and
Statements databases (an explicit grant; a Core admin gets nothing automatically). Placeholders:

```
python -m nvb_loans.admin      grant --subject nvb-user:<id>:<created> --role operations_admin --actor "ops:<ticket>" --reason "<reason>" --label <username>
python -m nvb_statements.admin grant --subject nvb-user:<id>:<created> --role operations_admin --actor "ops:<ticket>" --reason "<reason>" --label <username>
```

Without the grant the admin sees "Access not granted" on Loan management / Statement operations;
customer banking is unaffected. Reviewer retirement and its dry-run/apply steps are in the digital
branch's `docs/OPS_ADMIN_ROLE_MODEL.md`.

## Build and rollout notes (infrastructure)

* Build the Core image from this branch as usual; the frontend is compiled by the existing
  Containerfile stage. Roll out the digital branch's Loans and Statements images **together** with
  (or before) this Core revision; the old admin pages are gone, so an older Loans/Statements image
  would show "Unavailable"/"Access not granted" on the new admin pages.
* Golden v3 and running VMs are pinned; this branch changes nothing until infra builds and rolls it.
  Do not tag `v*` without going through the infra release process (tag pushes trigger
  `deploy-nvb.yml`).

## Rollback

Redeploy the previous Core revision (98effa3) — the old Operations page and reviewer workspace
return. No data or schema depends on this frontend.

## Validation run for this branch

* `npm run build` (TypeScript type-check + Vite production build): passed.
* Core route-protection regression via the guarded runner (`safe_core_tests.py`, temporary SQLite):
  `test_role_enforcement`, `test_protected_endpoints_require_session`,
  `test_csrf_required_for_state_changing_requests`, `test_cannot_read_other_customers_account`,
  `test_integration_disabled_by_default_registers_nothing` — 5 passed.
* Not run: browser/end-to-end tests against live or test services, PostgreSQL tests.
