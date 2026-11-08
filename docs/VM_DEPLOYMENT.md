# Deploying NVB on a single Linux VM (VMware)

This guide installs the NVB demo application and PostgreSQL on **one** VM, the
starting point of the modernization demo.

> **Scope and honesty note.** These steps were written for **RHEL 9.x** and
> RHEL 9-compatible distributions (e.g. Rocky Linux 9, AlmaLinux 9). They have
> **not** been executed on a live VM as part of this delivery. Package stream
> names differ between minor releases – each step includes a check command so
> you can confirm what your release offers before continuing. No other OS
> version is claimed to be supported.

Layout on the VM:

| Path | Contents | Owner / mode |
|---|---|---|
| `/opt/nvb/backend` | application code + built frontend (`app/static`) | `root:nvb`, read-only for the service |
| `/opt/nvb/venv` | Python 3.12 virtual environment | `root:nvb` |
| `/opt/nvb/scripts` | `nvb-admin.sh`, `backup.sh`, `restore.sh` | root |
| `/etc/nvb/nvb.env` | configuration and app DB password | `root:nvb 0640` |
| `/etc/systemd/system/nvb.service` | systemd unit (runs as `nvb`) | root |
| `/etc/nginx/conf.d/nvb.conf` | HTTPS reverse proxy | root |
| `/var/lib/pgsql/data` | PostgreSQL data | `postgres` |

## 0. Sizing

The demo baseline is **2 vCPU and 4 GiB RAM** for app + PostgreSQL together.
That is a *starting point for the degradation demo*, not a recommendation:
the load level at which this VM degrades depends on the host CPU, storage and
network. Calibrate it (see [SCALING_DEMO.md](SCALING_DEMO.md)) before the
live demo, and record the real numbers in `loadtest/results-template.md`.

## 1. Check the OS and available software

```bash
cat /etc/redhat-release
uname -m
nproc && free -h && df -h /
getenforce
```

```bash
sudo dnf -y update
sudo dnf list --available 'python3.12*'
sudo dnf module list postgresql nodejs nginx
```

You need: **Python 3.12**, **PostgreSQL 16**, **Node.js ≥ 20** (only to build
the frontend), **nginx**. If a stream is missing on your release, either
upgrade to a newer RHEL 9 minor release or build the frontend on another
machine and copy `frontend/dist` (see step 5).

## 2. Install packages

```bash
sudo dnf -y install python3.12 python3.12-pip git tar openssl policycoreutils-python-utils
sudo dnf -y module enable postgresql:16
sudo dnf -y install postgresql-server postgresql-contrib
sudo dnf -y module enable nodejs:22     # or nodejs:20 if 22 is not listed
sudo dnf -y install nodejs npm
sudo dnf -y install nginx
```

Verify versions:

```bash
python3.12 --version         # Python 3.12.x
psql --version               # psql (PostgreSQL) 16.x
node --version               # v20.x or v22.x
nginx -v
```

## 3. PostgreSQL

Initialise and start:

```bash
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
```

Force SCRAM password hashing (in `/var/lib/pgsql/data/postgresql.conf`):

```
password_encryption = scram-sha-256
listen_addresses = 'localhost'
```

Add the rules from [`deploy/vm/pg_hba.conf.snippet`](../deploy/vm/pg_hba.conf.snippet)
**above** the default rules in `/var/lib/pgsql/data/pg_hba.conf`, then:

```bash
sudo systemctl restart postgresql
```

Create the roles and database. `nvb_owner` owns the schema and is used only
for migrations / seed / reset; `nvb_app` (the running service) gets data
manipulation rights only – no DDL:

```bash
read -rsp 'nvb_owner password: ' OWNER_PW; echo
read -rsp 'nvb_app password: ' APP_PW; echo
sudo -u postgres psql -v owner_pw="$OWNER_PW" -v app_pw="$APP_PW" -f deploy/vm/postgresql-setup.sql
unset OWNER_PW APP_PW
```

Check:

```bash
psql "host=127.0.0.1 dbname=nvb user=nvb_app" -c 'select current_user;'
```

## 4. Get the code

```bash
sudo mkdir -p /usr/local/src && cd /usr/local/src
sudo git clone <your-repo-url> nvb      # or copy a release tarball
sudo chown -R "$USER": nvb && cd nvb
```

## 5. Install the application

[`deploy/vm/scripts/install.sh`](../deploy/vm/scripts/install.sh) creates the
`nvb` system user (no login shell), builds the frontend (as your user, not
root), copies the backend to `/opt/nvb/backend`, creates the venv with the
pinned `requirements.txt`, installs the systemd unit, the nginx site and a
config template. It does **not** migrate or seed.

```bash
sudo ./deploy/vm/scripts/install.sh
```

Frontend built elsewhere? Copy `frontend/dist` to `backend/app/static` before
running the script and comment out the build step in it.

## 6. Configure

```bash
sudoedit /etc/nvb/nvb.env
```

Set at least `NVB_DB_PASSWORD` (the `nvb_app` password) and
`NVB_METRICS_TOKEN` (`openssl rand -hex 32`). Keep
`NVB_ENVIRONMENT_LABEL="VMware VM"`. All variables are documented in
`backend/app/config.py` and [`deploy/vm/nvb.env.example`](../deploy/vm/nvb.env.example).
There are no default passwords: if `NVB_DB_PASSWORD` is wrong or missing the
service still starts, but `/health/ready` returns 503 and logs the DB error.

## 7. Migrate and seed (explicit, once)

```bash
sudo /opt/nvb/scripts/nvb-admin.sh check-db
sudo /opt/nvb/scripts/nvb-admin.sh migrate
```

Choose demo passwords (or omit them to have random ones generated into
`/root/nvb-demo-credentials.txt`, readable by root only):

```bash
read -rsp 'customer demo password: ' NVB_SEED_CUSTOMER_PASSWORD; echo
read -rsp 'load-test password: ' NVB_SEED_LOADTEST_PASSWORD; echo
read -rsp 'demo-operator password: ' NVB_SEED_DEMO_PASSWORD; echo
read -rsp 'ops admin password: ' NVB_SEED_ADMIN_PASSWORD; echo
export NVB_SEED_CUSTOMER_PASSWORD NVB_SEED_LOADTEST_PASSWORD NVB_SEED_DEMO_PASSWORD NVB_SEED_ADMIN_PASSWORD
sudo -E /opt/nvb/scripts/nvb-admin.sh seed
```

The seed is deterministic and refuses to run if data already exists. Use the
guarded reset to start over:

```bash
sudo /opt/nvb/scripts/nvb-admin.sh reset-demo-data --confirm "RESET NVB DEMO DATA"
```

## 8. Start the service

```bash
sudo systemctl enable --now nvb
systemctl status nvb --no-pager
curl -s http://127.0.0.1:8080/health/live
curl -s http://127.0.0.1:8080/health/ready
```

The unit runs `uvicorn` with two worker processes (`WEB_CONCURRENCY=2`, one
per vCPU) as the `nvb` user with systemd sandboxing (`ProtectSystem=strict`,
`NoNewPrivileges`, no capabilities). Prometheus multiprocess files live in
`/run/nvb/prometheus` and are cleared on every start.

## 9. nginx and HTTPS

Use a certificate from your internal CA if you have one. For an isolated demo,
a self-signed certificate is acceptable (browsers will warn):

```bash
sudo mkdir -p /etc/pki/nginx/private
sudo openssl req -x509 -newkey rsa:3072 -sha256 -days 365 -nodes \
  -keyout /etc/pki/nginx/private/nvb.key -out /etc/pki/nginx/nvb.crt \
  -subj "/CN=nvb.example.internal" -addext "subjectAltName=DNS:nvb.example.internal"
sudo chmod 600 /etc/pki/nginx/private/nvb.key
```

Edit `server_name` (and certificate paths if different) in
`/etc/nginx/conf.d/nvb.conf`. `/metrics` is only reachable from localhost (add
your Prometheus server's IP to the `allow` list if you scrape remotely).

SELinux must allow nginx to connect to the upstream on 127.0.0.1:8080:

```bash
sudo setsebool -P httpd_can_network_connect 1
sudo nginx -t && sudo systemctl enable --now nginx
```

## 10. Firewall

Only HTTP (redirects) and HTTPS are opened; PostgreSQL (5432) and the app port
(8080) stay local.

```bash
sudo systemctl enable --now firewalld
sudo firewall-cmd --permanent --add-service=http --add-service=https
sudo firewall-cmd --reload
sudo firewall-cmd --list-all
```

Browse to `https://nvb.example.internal/`.

## 11. Operations

| Task | Command |
|---|---|
| Start / stop / restart | `sudo systemctl start nvb` / `stop` / `restart` |
| Status | `systemctl status nvb --no-pager` |
| Follow logs (JSON, one line per event) | `journalctl -u nvb -f` |
| Errors in the last hour | `journalctl -u nvb --since -1h -o cat \| grep '"level": "ERROR"'` |
| Trace one request | `journalctl -u nvb -o cat \| grep '<X-Request-ID value>'` |
| nginx logs | `sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log` |
| PostgreSQL logs | `sudo journalctl -u postgresql -f` (and `/var/lib/pgsql/data/log/`) |
| Metrics | `curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/metrics` |
| Upgrade | pull new code, `sudo ./deploy/vm/scripts/install.sh`, `sudo /opt/nvb/scripts/nvb-admin.sh migrate`, `sudo systemctl restart nvb` |

### Backup

```bash
sudo -u postgres /opt/nvb/scripts/backup.sh                  # -> /var/lib/pgsql/backups/nvb/nvb-<UTC>.dump
```

Schedule it (e.g. a systemd timer or `sudo crontab -u postgres -e`:
`15 2 * * * /opt/nvb/scripts/backup.sh`). Copy backups off the VM – a backup on
the same disk does not survive the loss of the VM.

### Restore (destructive)

```bash
sudo systemctl stop nvb
sudo -u postgres /opt/nvb/scripts/restore.sh /var/lib/pgsql/backups/nvb/nvb-<UTC>.dump --confirm nvb
sudo systemctl start nvb
```

## 12. After migration to OpenShift Virtualization

The VM is migrated with external tooling (e.g. the Migration Toolkit for
Virtualization); the application does nothing special for it. On the migrated
VM:

1. Confirm services came up: `systemctl status postgresql nvb nginx`.
2. Change the label so the ops page reflects reality:
   `sudoedit /etc/nvb/nvb.env` → `NVB_ENVIRONMENT_LABEL="OpenShift VM"`, then
   `sudo systemctl restart nvb`.
3. Check the guest's IP/hostname – it may have changed. Update DNS / the
   nginx `server_name` and expose the VM (e.g. a Service + Route, see
   [OPENSHIFT_DEPLOYMENT.md](OPENSHIFT_DEPLOYMENT.md)).
4. Verify balances are unchanged (step 8 of the walkthrough).

Migrating the VM changes **where** it runs, not **how** it scales: it is still
one VM with the same vCPU/RAM and the same single application instance.

When the containerised app later connects to PostgreSQL on this VM, also set
`listen_addresses` to include the VM's cluster-facing address, enable `ssl`,
and add a `hostssl` rule for the cluster's pod/egress network (commented in
`pg_hba.conf.snippet`). Open 5432 **only** to that network:

```bash
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.128.0.0/14" port port="5432" protocol="tcp" accept'
sudo firewall-cmd --reload
```

(Replace the CIDR with your cluster's actual pod network or egress IPs.)
