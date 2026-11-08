#!/usr/bin/env bash
# Run an NVB admin CLI command on the VM with the service configuration, as the
# unprivileged `nvb` user. Run with sudo:
#
#   sudo /opt/nvb/scripts/nvb-admin.sh check-db
#   sudo /opt/nvb/scripts/nvb-admin.sh migrate
#   sudo /opt/nvb/scripts/nvb-admin.sh seed
#   sudo /opt/nvb/scripts/nvb-admin.sh reset-demo-data --confirm "RESET NVB DEMO DATA"
#
# migrate / seed / reset-demo-data need the nvb_owner password; it is prompted
# for (never stored) unless NVB_DB_MIGRATION_PASSWORD is already exported.
# seed: export NVB_SEED_CUSTOMER_PASSWORD etc. beforehand to choose demo
# passwords; otherwise generated passwords are written to
# /root/nvb-demo-credentials.txt (mode 0600) and nowhere else.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo." >&2
  exit 1
fi
CMD="${1:-}"
[ -n "${CMD}" ] || { echo "Usage: $0 <check-db|migrate|seed|reset-demo-data> [args]" >&2; exit 2; }

set -a
# shellcheck disable=SC1091
. /etc/nvb/nvb.env
set +a

case "${CMD}" in
  migrate|seed|reset-demo-data)
    export NVB_DB_MIGRATION_USER="${NVB_DB_MIGRATION_USER:-nvb_owner}"
    if [ -z "${NVB_DB_MIGRATION_PASSWORD:-}" ]; then
      read -rsp "Password for ${NVB_DB_MIGRATION_USER}: " NVB_DB_MIGRATION_PASSWORD; echo
      export NVB_DB_MIGRATION_PASSWORD
    fi
    ;;
esac
if [ "${CMD}" = "reset-demo-data" ]; then
  export NVB_ALLOW_DEMO_RESET=true
fi

EXTRA=()
WORKDIR=""
if [ "${CMD}" = "seed" ] && [[ " $* " != *" --credentials-file "* ]]; then
  WORKDIR="$(mktemp -d)"
  chown nvb:nvb "${WORKDIR}"
  chmod 0700 "${WORKDIR}"
  EXTRA=(--credentials-file "${WORKDIR}/demo-credentials.txt")
fi

cd /opt/nvb/backend
set +e
runuser -u nvb -- /opt/nvb/venv/bin/python -m app.cli "$@" "${EXTRA[@]}"
rc=$?
set -e

if [ -n "${WORKDIR}" ]; then
  if [ -s "${WORKDIR}/demo-credentials.txt" ]; then
    install -m 0600 -o root -g root "${WORKDIR}/demo-credentials.txt" /root/nvb-demo-credentials.txt
    echo "Demo credentials saved to /root/nvb-demo-credentials.txt (root only)."
  fi
  rm -rf "${WORKDIR}"
fi
exit "${rc}"
