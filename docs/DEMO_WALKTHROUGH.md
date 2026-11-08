# Live demo walkthrough (≈ 30–40 minutes)

Rehearse the whole sequence at least once on the real environments and fill in
[loadtest/results-template.md](../loadtest/results-template.md) with what you measure.
Never quote numbers you did not measure.

**Before the audience arrives**

* VMware VM running with `NVB_ENVIRONMENT_LABEL="VMware VM"`, data seeded, HTTPS working.
* `NVB_DEMO_WORKLOAD_ENABLED=true` on the environments used for the CPU demo only.
* Credentials file at hand (not on screen). Browser zoom ~110 %.
* Terminal tabs: `top`/`pidstat` on the VM, `oc get hpa,pods -w`, k6.
* Note the balances of `loadtest001`…`loadtest010` (step 8 compares them).

## 1. Normal banking activity (VMware VM)

1. Log in as `customer001`. Point out the **"Demo environment — synthetic data"** label.
2. Dashboard: greeting, EGP balances, total, recent transactions, income vs spending.
3. Accounts → an account → paginated history with masked numbers.
4. Transfers: pick account and beneficiary, enter `250.00`, **Review** (server-validated
   preview), **Confirm** → receipt with reference.
5. Transactions: filter by type "Transfer out", open the transaction detail, export CSV.
6. Log out, log in as `opsadmin` → Operations: environment **VMware VM**, version, serving
   instance, DB connected, request rate and p95 measured by this instance.

## 2. Increase load and show measured VM degradation

```bash
k6 run -e BASE_URL=https://nvb-vm.example.test -e PASSWORD=… loadtest/k6/02-ramp-up.js
k6 run -e BASE_URL=… -e PASSWORD=… loadtest/k6/04-cpu-pressure.js
```

* On the VM: `top` / `pidstat -u 5` show the uvicorn workers at ~100 % of the 2 vCPUs;
  `SELECT count(*) FROM pg_stat_activity` shows the DB is **not** the bottleneck (verify!).
* k6 summary and the Operations page show p95 latency rising and/or 429s from the bounded
  workload queue. Say exactly what was measured; identify the bottleneck before blaming it.

## 3. Same app on the migrated VM

The VM has been migrated to OpenShift Virtualization with external tooling (e.g. MTV).
Open the migrated VM's URL, log in as `customer001`, show the transfer from step 1 in the
history (data migrated with the disk), and the Operations page label **OpenShift VM**.
Make clear: same VM, same resources → same scaling limits. Migration changes the platform,
not the architecture.

## 4. Switch to the containerized deployment

```bash
oc apply -k deploy/openshift/overlays/single-replica   # baseline: 1 replica, no HPA
```

Containers use PostgreSQL **on the migrated VM**. Operations page shows
**OpenShift Containers** and the pod name as the instance. Run the same k6 script for the
one-replica comparison and record it.

## 5. Repeat the workload with HPA

```bash
oc apply -k deploy/openshift/overlays/scaling-demo     # HPA min 2 / max 6, CPU 60 %
oc get hpa nvb-app -w
k6 run -e BASE_URL=https://<route> -e PASSWORD=… loadtest/k6/04-cpu-pressure.js
```

Watch `TARGETS` climb above 60 % and `REPLICAS` increase. In the k6 output (and the
`X-NVB-Instance` distribution printed by script 05) more pod names appear. Compare p95 and
throughput with step 4 — whatever they actually are.

## 6. Delete a pod and observe recovery

```bash
k6 run -e BASE_URL=… -e PASSWORD=… loadtest/k6/05-pod-recovery.js &
oc delete pod "$(oc get pods -l app=nvb-app -o name | head -1)"
oc get pods -l app=nvb-app -w
```

Sessions survive (they live in PostgreSQL), the Deployment replaces the pod, readiness gates
traffic. Report the error count k6 actually observed — it may not be zero.

## 7. Reduce load and observe scale-down

Stop k6. After the 300 s scale-down stabilisation window the HPA steps replicas back
toward 2. Keep `oc get hpa -w` visible; mention the window is deliberate to avoid flapping.

## 8. Verify balances and transaction integrity

```bash
k6 run -e BASE_URL=… -e PASSWORD=… loadtest/k6/06-transfer-correctness.js
```

It performs concurrent transfers and idempotent retries, then checks every balance change
against the ledger and that total money in the test ring is conserved. Optionally on the DB:

```sql
-- every balance equals credits - debits from the ledger
SELECT a.id FROM accounts a
JOIN (SELECT account_id, SUM(CASE direction WHEN 'credit' THEN amount_minor ELSE -amount_minor END) s
      FROM ledger_entries GROUP BY account_id) l ON l.account_id = a.id
WHERE a.balance_minor <> l.s;          -- expect 0 rows
SELECT count(*) FROM accounts WHERE balance_minor < 0;   -- expect 0
```

Close with: correctness held under concurrency; scale-out helped **because** the measured
bottleneck was application CPU; the database stayed on the migrated VM throughout.
