#!/usr/bin/env bash
# setup.sh — One-shot deployment script for the Timetable Analysis server.
# Run as root on a fresh Ubuntu server. Expects all deploy files in the same directory.
set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────
APP_DIR="/opt/timetable"
VENV_DIR="$APP_DIR/.venv"
REPO_URL="https://github.com/maxmine2/aitimetable.git"
BRANCH="main"
SSL_DIR="/etc/ssl/timetable"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Helpers ──────────────────────────────────────────────────────────────────
log()   { echo -e "\n\033[1;32m>>>\033[0m $*"; }
warn()  { echo -e "\n\033[1;33m>>>\033[0m $*"; }
fail()  { echo -e "\n\033[1;31m>>>\033[0m $*" >&2; exit 1; }

# ── Pre-checks ──────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || fail "This script must be run as root."

if ! grep -qi 'ubuntu' /etc/os-release 2>/dev/null; then
    warn "This script is designed for Ubuntu. Proceeding anyway..."
fi

# Verify required deploy files are present
for f in certificate.pem private.pem timetable.nginx.conf timetable.service \
         timetable-update.service timetable-update.timer update.sh; do
    [ -f "$SCRIPT_DIR/$f" ] || fail "Required file missing: $f (expected in $SCRIPT_DIR)"
done

# ── 1. Install system packages ──────────────────────────────────────────────
log "Updating package lists and installing dependencies..."
apt-get update -qq
apt-get install -y -qq nginx python3 python3-venv git > /dev/null

# ── 2. Clone or update the repository ───────────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
    log "Repository already exists at $APP_DIR — pulling latest..."
    cd "$APP_DIR"
    git fetch origin "$BRANCH" --quiet
    git reset --hard "origin/$BRANCH"
else
    if [ -d "$APP_DIR" ]; then
        warn "$APP_DIR exists but is not a git repo — backing up and re-cloning..."
        mv "$APP_DIR" "$APP_DIR.bak.$(date +%s)"
    fi
    log "Cloning repository into $APP_DIR..."
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

# ── 3. Create Python virtual environment and install dependencies ───────────
log "Setting up Python virtual environment..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# ── 4. Install SSL certificates ─────────────────────────────────────────────
log "Installing SSL certificates to $SSL_DIR..."
mkdir -p "$SSL_DIR"
cp "$SCRIPT_DIR/certificate.pem" "$SSL_DIR/certificate.pem"
cp "$SCRIPT_DIR/private.pem"     "$SSL_DIR/private.pem"
chmod 600 "$SSL_DIR/certificate.pem" "$SSL_DIR/private.pem"
chown root:root "$SSL_DIR/certificate.pem" "$SSL_DIR/private.pem"

# ── 5. Configure nginx ──────────────────────────────────────────────────────
log "Configuring nginx..."
cp "$SCRIPT_DIR/timetable.nginx.conf" /etc/nginx/sites-available/timetable

# Enable site, disable default
ln -sf /etc/nginx/sites-available/timetable /etc/nginx/sites-enabled/timetable
rm -f /etc/nginx/sites-enabled/default

# Test and reload
nginx -t || fail "nginx configuration test failed!"
systemctl enable nginx
systemctl reload nginx
log "nginx configured and reloaded."

# ── 6. Install systemd units ────────────────────────────────────────────────
log "Installing systemd services and timer..."

# Copy the update script into the app directory
cp "$SCRIPT_DIR/update.sh" "$APP_DIR/update.sh"
chmod +x "$APP_DIR/update.sh"

# Copy systemd units
cp "$SCRIPT_DIR/timetable.service"        /etc/systemd/system/timetable.service
cp "$SCRIPT_DIR/timetable-update.service" /etc/systemd/system/timetable-update.service
cp "$SCRIPT_DIR/timetable-update.timer"   /etc/systemd/system/timetable-update.timer

systemctl daemon-reload

# ── 7. Set ownership ────────────────────────────────────────────────────────
log "Setting file ownership..."
chown -R www-data:www-data "$APP_DIR"

# ── 8. Enable and start services ────────────────────────────────────────────
log "Starting timetable service..."
systemctl enable --now timetable.service

log "Enabling auto-update timer..."
systemctl enable --now timetable-update.timer

# ── 9. Firewall (if ufw is active) ──────────────────────────────────────────
if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
    log "Configuring firewall rules..."
    ufw allow 80/tcp  > /dev/null
    ufw allow 443/tcp > /dev/null
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "============================================="
echo "  Deployment complete!"
echo "============================================="
echo ""
echo "  App directory:    $APP_DIR"
echo "  Virtual env:      $VENV_DIR"
echo "  SSL certs:        $SSL_DIR"
echo "  serve.py port:    8764 (proxied via nginx)"
echo ""
echo "  Services:"
echo "    timetable.service        — web server (auto-restarts)"
echo "    timetable-update.timer   — GitHub update check (~12 min)"
echo ""
echo "  Useful commands:"
echo "    systemctl status timetable"
echo "    systemctl status timetable-update.timer"
echo "    journalctl -u timetable -f"
echo "    journalctl -u timetable-update"
echo "    nginx -t && systemctl reload nginx"
echo ""
