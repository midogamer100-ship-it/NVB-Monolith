#!/usr/bin/env bash
# Restore the NVB database from a pg_dump custom-format archive.
# DESTRUCTIVE: replaces all current data in the target database.
#
#   sudo systemctl stop nvb
#   sudo -u postgres /opt/nvb/scripts/restore.sh/var/lib/pgsql/backups/nvb/nvb-<stamp>.dump --confirm nvb
#   sudo systemctl start nvb
set -euo pipefail

DUMP="${1:-}"
DB_NAME="${NVB_DB_NAME:-nvb}"

if [ -z "${DUMP}" ] || [ ! -f "${DUMP}" ]; then
  echo "Usage: $0 <dump-file> --confirm <database-name>" >&2
  exit 2
fi
if [ "${2:-}" != "--confirm" ] || [ "${3:-}" != "${DB_NAME}" ]; then
  echo "Refusing to restore: pass '--confirm ${DB_NAME}' to replace ALL data in '${DB_NAME}'." >&2
  exit 2
fi
if [ -f "${DUMP}.sha256" ]; then
  sha256sum --check --status "${DUMP}.sha256" || { echo "Checksum mismatch for ${DUMP}" >&2; exit 1; }
fi
if systemctl is-active --quiet nvb 2>/dev/null; then
  echo "Stop the application first: sudo systemctl stop nvb" >&2
  exit 1
fi

pg_restore --list "${DUMP}" >/dev/null
# --clean --if-exists drops existing objects; objects are re-owned by nvb_owner
# and nvb_app receives privileges through the default privileges / grants.
pg_restore --clean --if-exists --no-owner --role=nvb_owner --single-transaction \
  --exit-on-error --dbname="${DB_NAME}" "${DUMP}"
psql --dbname="${DB_NAME}" -v ON_ERROR_STOP=1 <<'SQL'
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nvb_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nvb_app;
SQL
echo "Restored ${DUMP} into ${DB_NAME}."
