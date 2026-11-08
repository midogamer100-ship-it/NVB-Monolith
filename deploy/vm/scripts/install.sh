#!/usr/bin/env bash
# Install / upgrade the NVB application on a RHEL 9-compatible VM.
# Run as root from the repository checkout:  sudo ./deploy/vm/scripts/install.sh
#
# Prerequisites (see docs/VM_DEPLOYMENT.md): python3.12, nodejs >= 20, npm,
# nginx, PostgreSQL 16 with the nvb database created via postgresql-setup.sql.
# This script does NOT run migrations or seed data - those are explicit steps.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PREFIX=/opt/nvb
PYTHON=${PYTHON:-python3.12}

command -v "${PYTHON}" >/dev/null || { echo "${PYTHON} not found" >&2; exit 1; }
"${PYTHON}" -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version' \
  || { echo "Python 3.12 required" >&2; exit 1; }

# 1. Dedicated non-root service account (no login shell, no home directory).
if ! id nvb >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir "${PREFIX}" --shell /sbin/nologin nvb
fi

# 2. Build the frontend as the invoking (non-root) user if possible.
if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
  sudo -u "${SUDO_USER}" "${REPO_ROOT}/deploy/vm/scripts/build-frontend.sh"
else
  "${REPO_ROOT}/deploy/vm/scripts/build-frontend.sh"
fi

# 3. Copy the application (code is owned by root, readable by the nvb group).
install -d -m 0755 "${PREFIX}"
rm -rf "${PREFIX}/backend.new"
cp -r "${REPO_ROOT}/backend" "${PREFIX}/backend.new"
rm -rf "${PREFIX}/backend.new/tests" "${PREFIX}/backend.new/.pytest_cache"
find "${PREFIX}/backend.new" -name '__pycache__' -prune -exec rm -rf {} +
rm -rf "${PREFIX}/backend.old"
[ -d "${PREFIX}/backend" ] && mv "${PREFIX}/backend" "${PREFIX}/backend.old"
mv "${PREFIX}/backend.new" "${PREFIX}/backend"
install -d -m 0755 "${PREFIX}/docs" "${PREFIX}/scripts"
cp "${REPO_ROOT}"/docs/*.md "${PREFIX}/docs/" 2>/dev/null || true
install -m 0755 "${REPO_ROOT}/deploy/vm/scripts/backup.sh" "${REPO_ROOT}/deploy/vm/scripts/restore.sh" \
  "${REPO_ROOT}/deploy/vm/scripts/nvb-admin.sh" "${PREFIX}/scripts/"

# 4. Virtual environment with pinned dependencies.
if [ ! -x "${PREFIX}/venv/bin/python" ]; then
  "${PYTHON}" -m venv "${PREFIX}/venv"
fi
"${PREFIX}/venv/bin/pip" install --no-cache-dir --upgrade pip
"${PREFIX}/venv/bin/pip" install --no-cache-dir -r "${PREFIX}/backend/requirements.txt"

chown -R root:nvb "${PREFIX}"
chmod -R u=rwX,g=rX,o= "${PREFIX}"
chmod 0755 "${PREFIX}" "${PREFIX}/scripts" && chmod 0755 "${PREFIX}"/scripts/*.sh   # postgres user runs backups

# 5. Configuration (never overwritten once present).
install -d -m 0750 -o root -g nvb /etc/nvb
if [ ! -f /etc/nvb/nvb.env ]; then
  install -m 0640 -o root -g nvb "${REPO_ROOT}/deploy/vm/nvb.env.example" /etc/nvb/nvb.env
  echo ">>> Edit /etc/nvb/nvb.env and set real values before starting the service."
fi

# 6. systemd unit and nginx site.
install -m 0644 "${REPO_ROOT}/deploy/vm/nvb.service" /etc/systemd/system/nvb.service
systemctl daemon-reload
if [ ! -f /etc/nginx/conf.d/nvb.conf ]; then
  install -m 0644 "${REPO_ROOT}/deploy/vm/nginx-nvb.conf" /etc/nginx/conf.d/nvb.conf
  echo ">>> Edit /etc/nginx/conf.d/nvb.conf (server_name, certificate paths)."
fi

echo "Installed to ${PREFIX}. Next: migrate, seed, then 'systemctl enable --now nvb'."
