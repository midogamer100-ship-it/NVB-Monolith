# Deploying NVB as containers on OpenShift

The containerised app runs from the **same codebase** as the VM install. In
this phase PostgreSQL stays on the **migrated VM** (OpenShift Virtualization);
only the application tier moves to pods.

> These manifests have **not** been applied to a live cluster as part of this
> delivery. They target OpenShift 4.x with the default `restricted-v2` SCC and
> OVN-Kubernetes. Validate them on your cluster (`oc apply --dry-run=server`)
> before the demo.

```
deploy/openshift/
├── base/                     Deployment, Service, Route, ConfigMap, SA, HPA, PDB, NetworkPolicies
├── overlays/
│   ├── demo-hpa/             default: HPA 2-6 replicas, workload disabled
│   ├── single-replica/       1 replica, no HPA/PDB, workload enabled (comparison)
│   └── scaling-demo/         HPA + synthetic workload enabled (isolated demo)
├── optional/monitoring/      Kustomize Component: ServiceMonitor + Thanos read access (verify first)
├── jobs/                     db-migrate-job.yaml, seed-job.yaml (run explicitly)
└── secret.example.yaml       template only – not referenced by any kustomization
```

## 1. Build, scan and push the image

The [`Containerfile`](../Containerfile) is multi-stage (UBI 9 Node.js 22 →
UBI 9 Python 3.12). The runtime image contains only the venv, the backend and
the built static assets; it runs as UID 1001 but works with any
OpenShift-assigned UID (group-0 permissions), listens on 8080, needs no
capabilities and runs with a read-only root filesystem (`/tmp` is an emptyDir).

```bash
podman build -t nvb-app:1.0.0 -f Containerfile .
```

Scan before pushing (pick what your organisation uses):

```bash
cd backend && pip-audit -r requirements.txt && cd ..
cd frontend && npm audit --omit=dev && cd ..
trivy image --severity HIGH,CRITICAL nvb-app:1.0.0      # or: grype nvb-app:1.0.0
```

With Red Hat Advanced Cluster Security: `roxctl image scan --image <registry>/nvb-app:1.0.0`
and enforce the result with an admission policy.

Push to the internal registry:

```bash
oc new-project nvb
oc registry login
REG=$(oc get route default-route -n openshift-image-registry -o jsonpath='{.spec.host}')
podman tag nvb-app:1.0.0 $REG/nvb/nvb-app:1.0.0
podman push $REG/nvb/nvb-app:1.0.0
```

(If the default registry route is not exposed, push to your external registry
and change `images:` in the overlay accordingly.)

## 2. Reach PostgreSQL on the migrated VM

The VM runs in its own namespace (here `nvb-vm`, VM name `nvb-vm`). Put a
Service in front of it so the pods use a stable DNS name:

```bash
virtctl expose vm nvb-vm -n nvb-vm --name nvb-postgres --port 5432 --target-port 5432
oc get svc nvb-postgres -n nvb-vm
```

→ `NVB_DB_HOST=nvb-postgres.nvb-vm.svc.cluster.local` (already the default in
`base/configmap.yaml`; change it if your names differ).

If the VM is attached to a secondary network (bridge / localnet) instead of the
pod network, use its IP (`oc get vmi nvb-vm -n nvb-vm -o jsonpath='{.status.interfaces[*].ipAddress}'`)
and replace the PostgreSQL egress rule in `base/networkpolicy.yaml` with the
commented `ipBlock` variant.

On the VM: PostgreSQL must listen on the VM's interface, require TLS
(`hostssl`), and `pg_hba.conf` / firewalld must allow only the cluster pod
network – see "After migration" in [VM_DEPLOYMENT.md](VM_DEPLOYMENT.md). Once
TLS is enabled set `NVB_DB_SSLMODE=require` (or `verify-full` with a CA
bundle) in the ConfigMap.

Check connectivity from inside the namespace:

```bash
oc run pgcheck -n nvb --rm -it --restart=Never --image=registry.redhat.io/rhel9/postgresql-16 \
  --labels=nvb.demo/db-client=true -- pg_isready -h nvb-postgres.nvb-vm.svc.cluster.local -p 5432
```

## 3. Secrets (never committed)

```bash
read -rsp 'nvb_app password: ' APP_PW; echo
oc create secret generic nvb-secrets -n nvb \
  --from-literal=NVB_DB_PASSWORD="$APP_PW" \
  --from-literal=NVB_METRICS_TOKEN="$(openssl rand -hex 32)"
read -rsp 'nvb_owner password: ' OWNER_PW; echo
oc create secret generic nvb-migration-secrets -n nvb \
  --from-literal=NVB_DB_MIGRATION_USER=nvb_owner \
  --from-literal=NVB_DB_MIGRATION_PASSWORD="$OWNER_PW"
unset APP_PW OWNER_PW
```

The application pods only receive `nvb-secrets`. The owner credentials are
mounted only into the migration/seed Jobs.

## 4. Apply the manifests

Edit the image in `overlays/*/kustomization.yaml` if it is not
`image-registry.openshift-image-registry.svc:5000/nvb/nvb-app:1.0.0`.

```bash
oc apply -k deploy/openshift/overlays/demo-hpa -n nvb --dry-run=server
oc apply -k deploy/openshift/overlays/demo-hpa -n nvb
```

The Deployment's pods need the `nvb-config` ConfigMap (created above) before
the migration Job can run, so applying first is fine – pods simply stay unready
until the schema exists.

## 5. Run migrations explicitly (once per release)

Migrations are **one explicit operation**, not an initContainer and not run by
each replica at startup. The CLI also takes a PostgreSQL advisory lock as a
second guard.

```bash
IMAGE=image-registry.openshift-image-registry.svc:5000/nvb/nvb-app:1.0.0
sed "s|NVB_IMAGE|${IMAGE}|" deploy/openshift/jobs/db-migrate-job.yaml | oc create -n nvb -f -
oc wait --for=condition=complete job/nvb-db-migrate -n nvb --timeout=300s
oc logs job/nvb-db-migrate -n nvb
oc delete job nvb-db-migrate -n nvb
```

When PostgreSQL on the migrated VM was already migrated and seeded on VMware,
this is a no-op (`alembic upgrade head` finds the schema current) and **no
seed is needed** – the data came with the VM. `jobs/seed-job.yaml` exists only
for a fresh, empty database.

## 6. Verify

```bash
oc get pods -l app=nvb-app -n nvb -o wide
oc get route nvb-app -n nvb -o jsonpath='https://{.spec.host}{"\n"}'
curl -sk https://$(oc get route nvb-app -n nvb -o jsonpath='{.spec.host}')/health/ready
oc get hpa nvb-app -n nvb
```

Sign in as the ops admin and open **Operations**: the environment label reads
"OpenShift Containers" and the instance identifier is the pod name. Reload a
few times: it changes between pods while the session continues (sessions live
in PostgreSQL).

## 7. Switching overlays during the demo

| Goal | Command |
|---|---|
| One replica, no HPA (baseline) | `oc delete hpa nvb-app -n nvb --ignore-not-found; oc delete pdb nvb-app -n nvb --ignore-not-found; oc apply -k deploy/openshift/overlays/single-replica -n nvb` |
| HPA + synthetic workload | `oc apply -k deploy/openshift/overlays/scaling-demo -n nvb` |
| Back to normal | `oc apply -k deploy/openshift/overlays/demo-hpa -n nvb` |

ConfigMap changes need a rollout to take effect:
`oc rollout restart deploy/nvb-app -n nvb`.

## 8. What the manifests enforce

| Concern | Where |
|---|---|
| Non-root, arbitrary UID, no privilege escalation, `drop: [ALL]`, seccomp `RuntimeDefault`, read-only root FS | `base/deployment.yaml` |
| Probes: startup + liveness on `/health/live` (process only), readiness on `/health/ready` (DB with short timeout) | `base/deployment.yaml` |
| Requests 500m / 512Mi, limits 1 CPU / 1Gi | `base/deployment.yaml` |
| HPA 2–6, CPU 60 %, scale-down stabilisation 300 s | `base/hpa.yaml` |
| PDB `minAvailable: 1` | `base/pdb.yaml` |
| Spread across nodes and zones (`ScheduleAnyway`) | `base/deployment.yaml` |
| No Kubernetes API token mounted, SA without RoleBindings | `base/serviceaccount.yaml` |
| Default-deny + documented allowances | `base/networkpolicy.yaml` |
| HTTPS Route, HTTP redirected | `base/route.yaml` |
| `/metrics` requires a bearer token | `NVB_METRICS_TOKEN` in `nvb-secrets` |

### NetworkPolicy allowances

| # | Direction | Peer | Port | Why |
|---|---|---|---|---|
| 1 | ingress | `openshift-ingress` namespace (router) | 8080/TCP | Route traffic |
| 2 | ingress | `openshift-user-workload-monitoring` | 8080/TCP | Prometheus scrape of `/metrics` (token protected) |
| 3 | egress | `openshift-dns` | 5353 + 53 UDP/TCP | Resolve the DB Service name |
| 4 | egress | virt-launcher pod of the VM (`vm.kubevirt.io/name=nvb-vm` in `nvb-vm`) or VM `ipBlock` | 5432/TCP | PostgreSQL on the migrated VM |

Everything else is denied in both directions (`nvb-default-deny`). Kubelet
probes are not affected on OVN-Kubernetes. Egress rules apply to pods labelled
`nvb.demo/db-client=true` (the app and the Jobs). If the VM's namespace has its
own default-deny policy, add a matching **ingress** allowance there for port
5432 from the `nvb` namespace.

## 9. Connection-pool sizing

Each app process holds a SQLAlchemy pool of `NVB_DB_POOL_SIZE` connections and
may open `NVB_DB_MAX_OVERFLOW` extra under burst. Containers run one process
per pod (`WEB_CONCURRENCY=1`).

| Consumer | Formula | With defaults |
|---|---|---|
| App pods at HPA maximum | 6 × (5 + 5) | 60 |
| Rolling-update surge pod (`maxSurge: 1`) | 1 × (5 + 5) | 10 |
| Original VM app (if still running) | 2 workers × (5 + 5) | 20 |
| Migration / seed Job | ~2 | 2 |
| Admin sessions (psql, backups) | | ~5 |
| **Total worst case** | | **97** |

PostgreSQL's default `max_connections` is 100 (some reserved for superusers),
so with the VM app still running you are at the limit. Options, in order of
preference for this demo:

1. **Stop the VM's own app service** once traffic moves to the containers
   (`sudo systemctl disable --now nvb` on the migrated VM) → worst case ≈ 77.
2. Keep `max_connections = 100`, reduce `NVB_DB_MAX_OVERFLOW` to 3 → 6 × 8 = 48.
3. Raise `max_connections` (e.g. 150) **and** check the VM has the memory for it.

`nvb_app` is also capped with `CONNECTION LIMIT 80` in
`postgresql-setup.sql`; adjust it together with the numbers above. Watch the
real usage with `nvb_db_pool_checked_out` and
`SELECT count(*) FROM pg_stat_activity WHERE datname='nvb';`.

Remember that more pods mean more concurrent DB work: if the measured
bottleneck becomes PostgreSQL on the VM, adding replicas will not help (see
[SCALING_DEMO.md](SCALING_DEMO.md)).

## 10. Optional: real metrics on the Operations page

Without monitoring integration the Operations page shows only this instance's
own counters and "Not configured" for cluster-wide values and replica count –
nothing is simulated.

To show measured cluster-wide request rate, p95 latency, error rate and the
available replica count:

1. A cluster admin enables user-workload monitoring
   (`enableUserWorkload: true` in `cluster-monitoring-config`).
2. Add the component to your overlay:

   ```yaml
   components:
     - ../../optional/monitoring
   ```

3. Apply. This creates a ServiceMonitor (bearer token from `nvb-secrets`), a
   separate `nvb-metrics-reader` ServiceAccount bound to `view` **in this
   namespace only**, mounts its token into the app, points
   `NVB_PROMETHEUS_URL` at the Thanos Querier tenancy port
   (`https://thanos-querier.openshift-monitoring.svc:9092`) and allows egress
   to it.

Verify on your cluster version: the tenancy port's authorisation requirements,
that the token Secret is populated (`oc get secret nvb-metrics-reader-token -o yaml`)
and contains `service-ca.crt`. The application still never calls the
Kubernetes API.

## 11. Troubleshooting

| Symptom | Check |
|---|---|
| Pods `CreateContainerConfigError` | `nvb-secrets` / `nvb-config` missing: `oc describe pod` |
| Pods running but `0/1 Ready` | `/health/ready` failing → DB: `oc logs deploy/nvb-app`, DNS name, NetworkPolicy, `pg_hba.conf`, VM firewall |
| `permission denied` writing files | something writes outside `/tmp`; the root FS is read-only by design |
| HPA `<unknown>/60%` | metrics not yet available (wait ~1 min) or no CPU request set |
| Login works then 401 on next request | cookie not returned: Route must be HTTPS (`NVB_COOKIE_SECURE=true`) |
| 401 on `/metrics` from Prometheus | ServiceMonitor token does not match `NVB_METRICS_TOKEN` |
