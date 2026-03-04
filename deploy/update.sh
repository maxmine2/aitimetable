#!/usr/bin/env bash
# update.sh — Checks GitHub for updates to aitimetable, pulls changes, and restarts the service.
set -euo pipefail

REPO_DIR="/opt/timetable"
REPO_URL="https://github.com/maxmine2/aitimetable.git"
BRANCH="main"
VENV_DIR="$REPO_DIR/.venv"
SERVICE_NAME="timetable"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

cd "$REPO_DIR"

# Ensure the directory is a git repo
if [ ! -d ".git" ]; then
    log "ERROR: $REPO_DIR is not a git repository."
    exit 1
fi

# Fetch latest changes
log "Fetching from origin..."
git fetch origin "$BRANCH" --quiet

LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
    log "Already up to date ($LOCAL_SHA)."
    exit 0
fi

log "Update found: $LOCAL_SHA -> $REMOTE_SHA"

# Pull changes
git reset --hard "origin/$BRANCH"
log "Code updated to $REMOTE_SHA."

# Reinstall dependencies (requirements.txt may have changed)
if [ -f "requirements.txt" ]; then
    log "Installing dependencies..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet -r requirements.txt
fi

# Fix ownership
chown -R www-data:www-data "$REPO_DIR"

# Restart the service
log "Restarting $SERVICE_NAME..."
systemctl restart "$SERVICE_NAME"
log "Service restarted successfully."
