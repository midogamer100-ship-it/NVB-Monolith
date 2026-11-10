#!/usr/bin/env bash
# Runs on the RHEL runner. Lists the pool IPs that are up right now (SSH port open)
# and writes an Ansible inventory. Scaled-down VMs are simply skipped.
set -euo pipefail

OUT="${1:-inventory.ini}"
found=0
{
  echo "[nvb_pool]"
  for ip in 10.11.11.91 10.11.11.92 10.11.11.93 10.11.11.94 10.11.11.95; do
    if timeout 3 bash -c "</dev/tcp/$ip/22" 2>/dev/null; then
      echo "$ip"
      found=$((found + 1))
    fi
  done
  echo
  echo "[nvb_pool:vars]"
  echo "ansible_user=nvbdeploy"
  echo "ansible_ssh_private_key_file=/home/ghrunner/.ssh/nvb_vm_key"
} > "$OUT"

cat "$OUT"
if [ "$found" -eq 0 ]; then
  echo "No pool VM is reachable on SSH." >&2
  exit 1
fi
