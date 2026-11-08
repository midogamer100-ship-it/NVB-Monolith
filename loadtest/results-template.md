# NVB load-test results

> Fill this in from **measured** runs only. Leave a cell empty (or write
> "not measured") rather than estimating. Keep the raw k6 summaries
> (`--summary-export`) and screenshots next to this file.

## Run metadata

| Field | Value |
|---|---|
| Date / time (UTC) | |
| Operator | |
| App version / image digest | |
| k6 version | |
| Load generator host (CPU / location) | |
| Script + parameters (exact command) | |
| Dataset (seed run date, users) | |

Use the **same script, parameters, dataset and load generator** for every column.

## Comparison

| Metric | VMware VM | Migrated OpenShift VM | One app replica (containers) | App with HPA (containers) |
|---|---|---|---|---|
| p95 latency – `GET /api/dashboard` (ms) | | | | |
| p95 latency – all requests (ms) | | | | |
| Throughput (requests/s, mean over steady phase) | | | | |
| Error rate (`http_req_failed`) | | | | |
| Replicas (min / max observed) | 1 VM | 1 VM | 1 | |
| Allocated resources | 2 vCPU / 4 GiB (VM total) | | 1 pod: req 500m / lim 1 CPU, 512Mi / 1Gi | per pod as left, × replicas |
| Observed app CPU (peak / steady) | | | | |
| Observed app memory (peak) | | | | |
| Observed PostgreSQL CPU (peak) | | | | |
| DB connections in use (peak) | | | | |
| Time to scale out (first new pod Ready) | n/a | n/a | n/a | |
| Time to scale back to min after load stops | n/a | n/a | n/a | |
| Measured bottleneck (CPU / DB / network / other) | | | | |
| Notes | | | | |

## How to collect each value

| Value | Source |
|---|---|
| p95 latency, throughput, error rate | k6 end-of-test summary: `http_req_duration` p(95), `http_reqs` rate, `http_req_failed` rate. Export with `k6 run --summary-export=results/<env>-<script>.json ...`. Throughput: use the steady phase only (exclude ramp stages) or report the k6 rate and say so. |
| Replicas | `oc get hpa nvb-app -w` and `oc get deploy nvb-app -o jsonpath='{.status.availableReplicas}'` (sample every few seconds into a file: `while true; do date -u +%T; oc get deploy nvb-app -o jsonpath='{.status.availableReplicas}{"\n"}'; sleep 5; done`). |
| Allocated resources | VM: `nproc`, `free -g` (and the VMware / VirtualMachine spec). Pods: `oc get deploy nvb-app -o jsonpath='{.spec.template.spec.containers[0].resources}'`. Migrated VM: `oc get vm <name> -o yaml` (CPU/memory). |
| Observed app CPU / memory (VM) | `pidstat -u -r -p "$(pgrep -d, -u nvb)" 5` or `top -b -d 5`, plus `sar -u 5` for whole-VM CPU. |
| Observed app CPU / memory (pods) | `oc adm top pods -l app=nvb-app` every 15 s, or the OpenShift console Observe → Metrics: `sum(rate(container_cpu_usage_seconds_total{namespace="<ns>",container="app"}[1m]))`. |
| Observed PostgreSQL CPU | On the (migrated) VM: `pidstat -u -C postgres 5`. |
| DB connections | `SELECT state, count(*) FROM pg_stat_activity WHERE datname='nvb' GROUP BY state;` and the app gauge `nvb_db_pool_checked_out`. |
| Scale-out / scale-in timing | Timestamps from the replica sampling loop or `oc get events --sort-by=.lastTimestamp | grep -i horizontal`. |
| Measured bottleneck | See docs/SCALING_DEMO.md, "Identify the real bottleneck". Record the evidence, not an assumption. |
