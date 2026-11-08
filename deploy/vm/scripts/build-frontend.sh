#!/usr/bin/env bash
# Build the React frontend and place the static assets where the backend serves
# them (backend/app/static). Run from anywhere inside the repository checkout.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${REPO_ROOT}/frontend"

node_major="$(node -p 'process.versions.node.split(".")[0]')"
if [ "${node_major}" -lt 20 ]; then
  echo "Node.js >= 20 required (found $(node --version))." >&2
  exit 1
fi

npm ci --no-audit --no-fund
npm run build

rm -rf "${REPO_ROOT}/backend/app/static"
cp -r "${REPO_ROOT}/frontend/dist" "${REPO_ROOT}/backend/app/static"
echo "Frontend built into backend/app/static"
