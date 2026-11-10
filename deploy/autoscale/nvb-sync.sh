#!/usr/bin/env bash
# NVB release sync. Installed on every pool VM as /usr/local/sbin/nvb-sync.sh and run as root.
#
#   nvb-sync.sh            -> install the newest v* tag (used at boot by nvb-sync.service)
#   nvb-sync.sh v1.2.3     -> install that tag (used by the Ansible rolling deploy)
#
# The release is installed with the repository's own deploy/vm/scripts/install.sh,
# which keeps /etc/nvb/nvb.env and the nginx site untouched.
# If GitHub is unreachable the installed release is kept and the script exits 0,
# so nvb.service still starts.
set -uo pipefail

REPO_URL="git@github.com:midogamer100-ship-it/NVB-Monolith.git"
STATE_DIR=/var/lib/nvb-deploy
SRC_DIR="$STATE_DIR/src"
RELEASE_FILE="$STATE_DIR/RELEASE"
export HOME=/root
export GIT_SSH_COMMAND="ssh -i /root/.ssh/nvb_github_deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=15"

log() { logger -s -t nvb-sync "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run as root." >&2; exit 1; }
install -d -m 0700 "$STATE_DIR"

# Only one sync at a time (boot sync and an Ansible deploy can overlap).
exec 9>"$STATE_DIR/lock"
flock 9

CURRENT=$(cat "$RELEASE_FILE" 2>/dev/null || echo none)

if [ ! -d "$SRC_DIR/.git" ]; then
  rm -rf "$SRC_DIR"
  if ! git clone --quiet "$REPO_URL" "$SRC_DIR"; then
    log "clone failed; keeping current release ($CURRENT)"
    exit 0
  fi
fi

if ! git -C "$SRC_DIR" fetch --quiet --tags --force --prune origin; then
  log "fetch failed; keeping current release ($CURRENT)"
  exit 0
fi

TAG="${1:-}"
if [ -z "$TAG" ]; then
  TAG=$(git -C "$SRC_DIR" tag -l 'v*' --sort=-v:refname | head -n1)
fi
if [ -z "$TAG" ]; then
  log "no v* release tags yet; keeping current code"
  exit 0
fi
if ! git -C "$SRC_DIR" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  log "tag $TAG does not exist in the repository"
  exit 1
fi

if [ "$CURRENT" = "$TAG" ]; then
  log "already on $TAG"
  exit 0
fi

log "starting install of $TAG (current: $CURRENT)"
git -C "$SRC_DIR" checkout --quiet --force "$TAG" || { log "checkout of $TAG failed"; exit 1; }
git -C "$SRC_DIR" clean -ffdxq

# SUDO_USER is removed so install.sh builds the frontend as root inside $SRC_DIR.
if ! (cd "$SRC_DIR" && env -u SUDO_USER bash ./deploy/vm/scripts/install.sh); then
  log "install.sh failed for $TAG"
  exit 1
fi

echo "$TAG" > "$RELEASE_FILE"
log "installed $TAG"
