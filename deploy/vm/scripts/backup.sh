#!/usr/bin/env bash
# Logical backup of the NVB database (custom format, compressed).
#   sudo -u postgres /opt/nvb/scripts/backup.sh [backup-dir]
# Run as the postgres OS user (peer authentication on the local socket).
set -euo pipefail

BACKUP_DIR="${1:-/var/lib/pgsql/backups/nvb}"
DB_NAME="${NVB_DB_NAME:-nvb}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR}/nvb-${STAMP}.dump"

umask 077
mkdir -p "${BACKUP_DIR}"
pg_dump --format=custom --compress=6 --no-owner --dbname="${DB_NAME}" --file="${OUT}"
pg_restore --list "${OUT}" >/dev/null   # sanity check: archive is readable
sha256sum "${OUT}" > "${OUT}.sha256"
echo "Backup written: ${OUT}"

# Keep the 14 most recent backups.
ls -1t "${BACKUP_DIR}"/nvb-*.dump 2>/dev/null | tail -n +15 | while read -r old; do
  rm -f -- "${old}" "${old}.sha256"
done
