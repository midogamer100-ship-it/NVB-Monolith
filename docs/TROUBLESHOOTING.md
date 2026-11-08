# Troubleshooting

| Symptom | Likely cause | Check / fix |
| --- | --- | --- |
| Login always fails in local http, cookie never set | `NVB_COOKIE_SECURE=true` over plain http | Use HTTPS, or `NVB_COOKIE_SECURE=false` **only** on localhost |
| Every POST returns 403 "Missing or invalid CSRF token" | Client not sending `X-CSRF-Token`, or token from another session | Re-login; k6 scripts store the token per VU from the login response |
| 429 "Too many failed sign-in attempts" | Login throttle (per username or per IP, shared in DB) | Wait for the window (15 min) or admin → Operations → *Clear sign-in lockout*. During load tests behind one NAT IP, raise `NVB_LOGIN_MAX_FAILURES_PER_IP` |
| Redirected to login with "session expired" | Idle (15 min) or absolute (8 h) timeout | Expected. Adjust `NVB_SESSION_*_TIMEOUT_MINUTES` for long demos |
| `/health/ready` 503, `/health/live` 200 | DB unreachable or slow | `python -m app.cli check-db`; firewall/NetworkPolicy to port 5432; `pg_hba.conf`; DB host in ConfigMap |
| Pods `Running` but `0/1 READY` on OpenShift | Readiness failing — almost always DB connectivity | `oc logs`, `oc rsh <pod> curl -s localhost:8080/health/ready`, egress NetworkPolicy, VM Service/IP |
| `CrashLoopBackOff`, "read-only file system" | Something writing outside `/tmp` | Ensure the `/tmp` emptyDir mount exists; `PYTHONDONTWRITEBYTECODE=1` is set in the image |
| Seed: "Database already contains data" | Seed only runs on an empty DB | Use the guarded `reset-demo-data` (see README) |
| Seed in a container: permission denied on credentials file | Read-only root filesystem | Pass `--credentials-file /tmp/creds.txt` |
| `psycopg.OperationalError: too many connections` | Pool size × replicas exceeds `max_connections` | See pool sizing in [OPENSHIFT_DEPLOYMENT.md](OPENSHIFT_DEPLOYMENT.md); lower `NVB_DB_POOL_SIZE`/`NVB_DB_MAX_OVERFLOW` or raise `max_connections` |
| `permission denied for table …` as `nvb_app` | Tables created by a role without default privileges | Run migrations as `nvb_owner`; re-run the grants in `deploy/vm/postgresql-setup.sql` |
| `/metrics` 401/403 | Token missing | `curl -H "Authorization: Bearer $NVB_METRICS_TOKEN" …`; ServiceMonitor must reference the token Secret |
| `/metrics` numbers jump around on the VM | Several workers without multiprocess mode | Set `PROMETHEUS_MULTIPROC_DIR` (the systemd unit does) |
| Demo workload returns 404 | Feature flag off (by design) | `NVB_DEMO_WORKLOAD_ENABLED=true` on the demo environment only, restart |
| Demo workload returns 403 | Not a `demo` role user | Use `demoload01`…`demoload10` |
| Demo workload mostly 429 | Per-process concurrency limit reached | Expected under saturation; it is a real, bounded queue. Tune `NVB_DEMO_WORKLOAD_MAX_CONCURRENCY` deliberately and document it |
| HPA shows `<unknown>/60%` | Metrics server not reporting, or no CPU request | `oc describe hpa nvb-app`; requests are set in the Deployment |
| HPA never scales out | Load not CPU-bound on the app (e.g. DB-bound) | Measure first (`oc adm top pods`, DB CPU, `pg_stat_activity`). CPU-HPA is the wrong tool for a DB bottleneck |
| Scale-down "takes forever" | 300 s stabilisation window | Expected; it prevents flapping |
| Operations page shows "Not configured" for replicas | Optional monitoring integration not installed | Expected. See `deploy/openshift/optional/monitoring/` |
| Route returns 503 | No ready endpoints, or ingress NetworkPolicy label mismatch | `oc get endpoints nvb-app`; check the router namespace label used in `networkpolicy.yaml` |
| Frontend shows "frontend has not been built" | Static assets missing | `npm run build` and set `NVB_STATIC_DIR`, or use the container image |
| Windows: `pip install` fails with "No such file or directory" deep in site-packages | 260-character path limit | Create the venv in a short path (e.g. `C:\venvs\nvb`) |

## Useful commands

```bash
# VM
sudo systemctl status nvb ; sudo journalctl -u nvb -f -o cat | jq .
sudo -u postgres psql -d nvb -c "SELECT state, count(*) FROM pg_stat_activity GROUP BY 1;"

# OpenShift
oc get pods,hpa,pdb -l app=nvb-app
oc logs deploy/nvb-app --all-containers --prefix | jq -R 'fromjson? // .'
oc adm top pods -l app=nvb-app
oc describe hpa nvb-app

# Correlate one request across logs
curl -sk -H "X-Request-ID: demo-trace-0001" https://<host>/health/ready -D - -o /dev/null
oc logs -l app=nvb-app --tail=-1 | grep demo-trace-0001
```
