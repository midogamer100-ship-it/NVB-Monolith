# Load testing NVB with k6

All scripts live in [`loadtest/k6/`](../loadtest/k6). They talk to the public
HTTP API exactly like the browser does (cookie session + CSRF header), so the
same scripts run against the VMware VM, the migrated OpenShift VM and the
OpenShift Route.

> Synthetic data only. Run these against the demo environment, never against
> a system holding real data. Results depend on hardware, network and the
> load generator: **calibrate**, and never copy numbers between environments.

## Prerequisites

* k6 v0.50 or newer (`k6 version`). Install from https://grafana.com/docs/k6/latest/set-up/install-k6/.
* The database seeded with `python -m app.cli seed` (creates `loadtest001..100`
  and `demoload01..10`). Their passwords are the `NVB_SEED_LOADTEST_PASSWORD` /
  `NVB_SEED_DEMO_PASSWORD` values you set, or the generated values in the seed
  credentials file.
* A load generator that is **not** the system under test (a separate VM or
  laptop). Running k6 on the app VM steals the CPU you are trying to measure.

Keep passwords out of shell history:

```bash
read -rsp 'loadtest password: ' K6_PASSWORD; echo; export K6_PASSWORD
read -rsp 'demo password: ' K6_DEMO_PASSWORD; echo; export K6_DEMO_PASSWORD
```

…and pass them with `-e PASSWORD="$K6_PASSWORD"`.

## Common parameters

| Variable | Default | Meaning |
|---|---|---|
| `BASE_URL` | `http://localhost:8080` | Target, e.g. `https://nvb.example.internal` or the Route host |
| `PASSWORD` | – (required) | Password of the `loadtestNNN` users |
| `DEMO_PASSWORD` | – (required by 04) | Password of the `demoloadNN` users |
| `USER_PREFIX` / `USER_PAD` / `USER_COUNT` | `loadtest` / `3` / `100` | Which seeded users to rotate through |
| `VUS`, `TARGET_VUS`, `DURATION`, `RATE`… | per script | Load shape (see the header comment of each script) |
| `THINK_MIN` / `THINK_MAX` | `1` / `3` | Think time (seconds) between page views |
| `INSECURE_TLS` | `false` | `true` to accept a self-signed demo certificate |

## Scripts

| Script | Type | Purpose |
|---|---|---|
| `01-normal-activity.js` | read-heavy performance | Baseline browsing (dashboard, accounts, transactions) |
| `02-ramp-up.js` | read-heavy performance | 5 equal steps up to `TARGET_VUS`; find where latency bends |
| `03-salary-day-spike.js` | read + login performance | Open-model arrival-rate spike with fresh logins |
| `04-cpu-pressure.js` | synthetic CPU demo | Sustained bounded statement-analysis workload + normal browsing (needs `NVB_DEMO_WORKLOAD_ENABLED=true`) |
| `05-pod-recovery.js` | resilience | Constant traffic while you `oc delete pod`; checks error rate, re-logins and per-pod distribution |
| `06-transfer-correctness.js` | **correctness** | Concurrent transfers + idempotent retries + key-reuse conflict, with ledger/balance verification in teardown |

Performance scripts (01–05) never move money. The correctness script (06)
moves small amounts only between `loadtest001..N` and must not run at the same
time as anything else that uses those users.

## Examples

```bash
k6 run -e BASE_URL=https://nvb.example.internal -e PASSWORD="$K6_PASSWORD" \
  -e VUS=20 -e DURATION=5m --summary-export=results/vm-01.json loadtest/k6/01-normal-activity.js
```

```bash
k6 run -e BASE_URL=https://nvb.example.internal -e PASSWORD="$K6_PASSWORD" \
  -e TARGET_VUS=200 -e STEP_DURATION=2m --summary-export=results/vm-02.json loadtest/k6/02-ramp-up.js
```

```bash
k6 run -e BASE_URL=https://nvb-app-nvb.apps.example.com -e PASSWORD="$K6_PASSWORD" \
  -e DEMO_PASSWORD="$K6_DEMO_PASSWORD" -e ANALYSIS_RATE=4 -e BROWSE_VUS=20 -e DURATION=15m \
  --summary-export=results/hpa-04.json loadtest/k6/04-cpu-pressure.js
```

```bash
k6 run -e BASE_URL=https://nvb-app-nvb.apps.example.com -e PASSWORD="$K6_PASSWORD" \
  -e TRANSFER_USERS=20 -e VUS_PER_USER=2 -e DURATION=2m loadtest/k6/06-transfer-correctness.js
```

Exit code 0 from script 06 means every check passed and
`nvb_integrity_violations` stayed at 0. Insufficient-funds handling and the
atomicity of a single transfer are covered by the backend automated tests.

## Resetting demo data between runs

Script 06 changes balances; scripts 03 and 05 create many sessions. To return
to the deterministic seed state (destroys all demo data – guarded):

```bash
sudo /opt/nvb/scripts/nvb-admin.sh reset-demo-data --confirm "RESET NVB DEMO DATA"
```

(The wrapper prompts for the `nvb_owner` password and sets
`NVB_ALLOW_DEMO_RESET=true` for that single invocation only.)

(Compose: `docker compose run --rm -e NVB_ALLOW_DEMO_RESET=true app python -m app.cli reset-demo-data --confirm "RESET NVB DEMO DATA"`.)

## Recording results

Copy [`loadtest/results-template.md`](../loadtest/results-template.md) per
campaign and fill it in from the k6 summaries and the resource measurements
described there. Do not fill cells you did not measure.
