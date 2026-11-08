# Repeatable scaling demonstration

This is the measured part of the story: show where a constrained VM degrades,
show that the migrated VM behaves the same, then show that the
**containerised** application can add replicas when – and only when – the
bottleneck is application CPU.

Two statements to make explicitly in the demo:

* **Migrating a VM does not add scaling.** OpenShift Virtualization runs the
  same single VM with the same vCPU/RAM and the same one application
  instance. Expect broadly the same behaviour before and after migration
  (hardware differences between the VMware host and the OpenShift node may
  shift the numbers either way – measure, don't assume).
* **CPU-based autoscaling helps only when the measured bottleneck is
  application CPU.** If latency is driven by PostgreSQL, locks, disk, network
  or the load generator itself, more app pods will not help and may make the
  database worse.

Nothing in the application fakes load: there are no sleeps, injected failures
or hard-coded slow paths. Degradation comes from real work on constrained CPU.

## The synthetic workload

`POST /api/demo/statement-analysis` analyses a **synthetic** statement
(generated from a seeded PRNG – no customer data) and runs a bounded
Monte-Carlo projection in pure Python. Each call uses one CPU core for a
fixed, server-defined amount of work.

| Safeguard | Setting |
|---|---|
| Off unless explicitly enabled; route not registered otherwise | `NVB_DEMO_WORKLOAD_ENABLED=false` (default) |
| Only the `demo` role (`demoload01..10`) | server-side role check |
| No free-form input: `profile` ∈ {standard, heavy}, `months` 1–12, `seed` integer | request validation |
| Per-process concurrency cap; excess waits ≤ queue timeout then gets HTTP 429 | `NVB_DEMO_WORKLOAD_MAX_CONCURRENCY`, `NVB_DEMO_WORKLOAD_QUEUE_TIMEOUT_SECONDS` |
| Hard compute time budget per call (HTTP 503 if exceeded) | `NVB_DEMO_WORKLOAD_MAX_SECONDS` |
| Fixed simulation count | `NVB_DEMO_WORKLOAD_SIMULATIONS` |

The UI labels it "Synthetic workload" and it appears only for demo-role users
when enabled. Enable it only in the isolated demo environment.

## 0. Calibrate first (before the audience arrives)

1. Deploy on the VMware VM (2 vCPU / 4 GiB baseline) with
   `NVB_DEMO_WORKLOAD_ENABLED=true`, restart.
2. Run `04-cpu-pressure.js` for 3 minutes at `ANALYSIS_RATE=1`, then 2, 4, 6…
   Note the rate at which browse p95 rises clearly and VM CPU is pinned near
   100 %. That is your demo rate – typically a little above the knee.
3. Check a single call's `compute_ms` (in the response and the
   `nvb_workload_compute_ms` trend). If one call takes much more than ~1 s,
   lower `NVB_DEMO_WORKLOAD_SIMULATIONS`; if much less than ~100 ms, raise it.
4. Keep the load generator outside the VM and confirm its own CPU stays well
   below saturation (otherwise you are measuring k6).

Record every calibration run in `loadtest/results-template.md`.

## 1. VMware VM under constrained CPU and memory

Confirm the allocation:

```bash
nproc; free -h
```

(To constrain further without touching the VM spec you can cap the service:
`sudo systemctl set-property --runtime nvb.service CPUQuota=150% MemoryMax=1G` –
remove with `sudo systemctl revert nvb.service`. State clearly in the demo if you
do this.)

Start observation on the VM in separate terminals:

```bash
sar -u 5                                         # whole-VM CPU (sysstat)
pidstat -u -r -p "$(pgrep -d, -u nvb)" 5          # app worker processes (user nvb)
pidstat -u -r -C postgres 5                      # PostgreSQL backends
vmstat 5                                         # run queue (r), swapping (si/so), iowait (wa)
sudo -u postgres psql nvb -c "select state, wait_event_type, count(*) from pg_stat_activity where datname='nvb' group by 1,2;"
```

Run the ramp, then the CPU-pressure test:

```bash
k6 run -e BASE_URL=https://nvb.example.internal -e INSECURE_TLS=true -e PASSWORD="$K6_PASSWORD" \
  -e TARGET_VUS=150 -e STEP_DURATION=2m --summary-export=results/vmware-02.json loadtest/k6/02-ramp-up.js
k6 run -e BASE_URL=https://nvb.example.internal -e INSECURE_TLS=true -e PASSWORD="$K6_PASSWORD" \
  -e DEMO_PASSWORD="$K6_DEMO_PASSWORD" -e ANALYSIS_RATE=<calibrated> -e DURATION=10m \
  --summary-export=results/vmware-04.json loadtest/k6/04-cpu-pressure.js
```

## 2. Identify the real bottleneck

Look at evidence, not at the latency graph alone:

| Observation | Points to |
|---|---|
| `uvicorn` processes ≈ 100 % of a core each, `vmstat r` > vCPU count, postgres CPU low, few `active` sessions in `pg_stat_activity` | **Application CPU** → horizontal scaling of the app can help |
| `postgres` processes high CPU, many `active` sessions, `wait_event_type = Lock` or `IO` | **Database** → app replicas will not help; tune queries/indexes or give the DB more resources |
| `wa` (iowait) high in `vmstat`/`sar` | **Storage** |
| `si`/`so` non-zero, memory near full | **Memory** pressure |
| `nvb_db_pool_checked_out` at pool size + overflow, pool timeouts in logs | **Connection pool** → check DB first, then pool sizing |
| k6 host CPU high / `dropped_iterations` > 0 | **Load generator**, not the app |

For the synthetic workload you should see app CPU saturation. Write down what
you saw – that is the justification for the HPA later.

## 3. The migrated VM (OpenShift Virtualization)

After the VM is migrated with external tooling, set
`NVB_ENVIRONMENT_LABEL="OpenShift VM"`, restart the service and repeat **exactly**
the same k6 commands against the migrated VM's address. Expect the same shape
of degradation: it is still one VM with the same resources. Note any
difference and its likely cause (e.g. different host CPU model).

## 4. Containers, one replica, no HPA

```bash
oc delete hpa nvb-app -n nvb --ignore-not-found
oc delete pdb nvb-app -n nvb --ignore-not-found
oc apply -k deploy/openshift/overlays/single-replica -n nvb
oc rollout status deploy/nvb-app -n nvb
```

The pod has a request of 500m and a limit of 1 CPU; one uvicorn process.
Observe:

```bash
watch -n 5 'oc adm top pods -l app=nvb-app -n nvb'
```

Run the same `04-cpu-pressure.js` against the Route. The single pod is
throttled at its 1-CPU limit and latency rises – comparable to the VM, now
with a known, explicit resource limit.

## 5. Enable the HPA and repeat

```bash
oc apply -k deploy/openshift/overlays/scaling-demo -n nvb
oc rollout status deploy/nvb-app -n nvb
oc get hpa nvb-app -n nvb
```

HPA: min 2, max 6, target 60 % CPU of the 500m request (≈ 300m per pod),
scale-up up to +2 pods or +100 % every 30 s, scale-down at most 1 pod per
minute after a 300 s stabilisation window. These are starting values –
tune them from your measurements.

In separate terminals:

```bash
oc get hpa nvb-app -n nvb -w
oc get pods -l app=nvb-app -n nvb -w
oc get events -n nvb --field-selector involvedObject.kind=HorizontalPodAutoscaler -w
```

Run the identical k6 command. Expect, in order: CPU above target → HPA raises
desired replicas → new pods pass the startup and readiness probes → the Route
spreads requests (watch `X-NVB-Instance` / the Operations page instance id) →
per-pod CPU and browse p95 come down. If replicas reach 6 and latency is still
high, you have hit the configured ceiling or a different bottleneck – check
PostgreSQL on the VM (section 2) before raising `maxReplicas`.

## 6. Pod deletion during load

With traffic running (`05-pod-recovery.js`), delete one pod:

```bash
oc delete pod $(oc get pods -l app=nvb-app -n nvb -o jsonpath='{.items[0].metadata.name}') -n nvb
```

The Deployment replaces it; the other replicas keep serving and sessions
survive because they are stored in PostgreSQL (`nvb_relogins` stays 0).

## 7. Scale-down

Stop k6. CPU drops immediately, but replicas are removed only after the
300-second stabilisation window and then one per minute down to 2. Keep
`oc get hpa -w` on screen to show this honestly – it is intentional damping,
not a failure to scale down.

## 8. Integrity check after the demo

```bash
k6 run -e BASE_URL=... -e PASSWORD="$K6_PASSWORD" loadtest/k6/06-transfer-correctness.js
```

and in the database on the VM:

```sql
-- no negative balances
SELECT count(*) FROM accounts WHERE balance_minor < 0;
-- every completed transfer has exactly one debit and one credit of the same amount
SELECT t.reference FROM transfers t
  LEFT JOIN ledger_entries d ON d.transfer_id = t.id AND d.direction = 'debit'
  LEFT JOIN ledger_entries c ON c.transfer_id = t.id AND c.direction = 'credit'
 WHERE t.status = 'completed'
   AND (d.id IS NULL OR c.id IS NULL OR d.amount_minor <> t.amount_minor OR c.amount_minor <> t.amount_minor);
-- failed transfers moved no money
SELECT count(*) FROM ledger_entries l JOIN transfers t ON t.id = l.transfer_id WHERE t.status = 'failed';
```

All three queries should return 0 rows / 0.

## Fill in the results

Use `loadtest/results-template.md` for the four columns (VMware VM, migrated
VM, one replica, HPA). Only measured values; leave the rest empty.
