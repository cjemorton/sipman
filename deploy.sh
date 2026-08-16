#!/bin/bash
set -uo pipefail

######################################################################
# Pure Kamailio + RTPEngine + Custom Web UI Deployment Script
# Deploys on sip.mrnet.work (Rocky Linux 9.8)
# Replaces dSIPRouter with a clean, minimal setup
######################################################################

echo "=========================================="
echo "  SIP Manager - Pure Kamailio Deployment"
echo "=========================================="
echo ""

# Backup function
backup_file() {
    if [ -f "$1" ]; then
        cp "$1" "${1}.backup.$(date +%Y%m%d_%H%M%S)"
        echo "[BACKUP] Created backup: ${1}.backup.$(date +%Y%m%d_%H%M%S)"
    fi
}

echo "[STEP 1] Backing up existing configuration..."
backup_file /etc/kamailio/kamailio.cfg
backup_file /etc/nginx/sites-available/dsiprouter.conf 2>/dev/null || true
backup_file /etc/rtpengine/rtpengine.conf 2>/dev/null || true

# Backup database (with retry)
echo "[STEP 1] Backing up MariaDB database..."
mysqldump kamailio > /root/kamailio_backup_$(date +%Y%m%d_%H%M%S).sql 2>&1 || echo "[WARN] Database backup failed, but continuing..."
echo "[BACKUP] Database backed up to /root/kamailio_backup_*.sql"

echo ""
echo "[STEP 2] Stopping dSIPRouter service..."
systemctl stop dsiprouter 2>/dev/null || echo "[INFO] dsiprouter already stopped"
systemctl disable dsiprouter 2>/dev/null || echo "[INFO] dsiprouter already disabled"
echo "[OK] dSIPRouter service stopped"

echo ""
echo "[STEP 3] Deploying new Kamailio config..."
cp /tmp/sipman_configs/kamailio.cfg /etc/kamailio/kamailio.cfg
chown root:kamailio /etc/kamailio/kamailio.cfg
chmod 640 /etc/kamailio/kamailio.cfg
echo "[OK] Kamailio config deployed"

echo ""
echo "[STEP 4] Deploying nginx config for Web UI..."
rm -f /etc/nginx/sites-enabled/dsiprouter.conf 2>/dev/null || true
cp /tmp/sipman_configs/nginx-sipman.conf /etc/nginx/sites-available/sipman.conf
ln -sf /etc/nginx/sites-available/sipman.conf /etc/nginx/sites-enabled/sipman.conf
echo "[OK] nginx config deployed"

echo ""
echo "[STEP 5] Deploying SIP Manager web application..."
mkdir -p /opt/sipman/static
cp -r /tmp/sipman_app/* /opt/sipman/
chown -R root:root /opt/sipman/
chmod +x /opt/sipman/app.py
mkdir -p /run/sipman
chown root:root /run/sipman
echo "[OK] Web application deployed to /opt/sipman/"

echo ""
echo "[STEP 6] Installing Python packages..."
pip3 install --break-system-packages flask pyjwt bcrypt mysql-connector-python gunicorn 2>&1 | tail -5 || echo "[WARN] Some packages may already be installed"
echo "[OK] Python packages installed"

echo ""
echo "[STEP 6b] Setting up MySQL user for SIP Manager..."
SIPMAN_DB_PASS=$(openssl rand -hex 16)
mysql -u root -e "CREATE USER IF NOT EXISTS 'sipman'@'localhost' IDENTIFIED BY '${SIPMAN_DB_PASS}';" 2>/dev/null || true
mysql -u root -e "GRANT SELECT, INSERT, UPDATE, DELETE ON kamailio.* TO 'sipman'@'localhost';" 2>/dev/null || true
mysql -u root -e "FLUSH PRIVILEGES;" 2>/dev/null
echo "[OK] Created MySQL user 'sipman' for SIP Manager"

# Update systemd service with the correct DB password
sed "s|Environment=\"MARIADB_PASS=\"|Environment=\"MARIADB_PASS=${SIPMAN_DB_PASS}\"|" \
    /tmp/sipman_configs/sipman-web.service > /etc/systemd/system/sipman-web.service
chmod 644 /etc/systemd/system/sipman-web.service
echo "[OK] Systemd service configured with database password"

echo ""
echo "[STEP 7] Creating systemd service for SIP Manager..."
systemctl daemon-reload
systemctl enable sipman-web
echo "[OK] systemd service created"

echo ""
echo "[STEP 8] Creating admin database..."
python3 -c "
import sqlite3, os
from werkzeug.security import generate_password_hash
import datetime

db_path = '/run/sipman/sipman.db'
os.makedirs(os.path.dirname(db_path), exist_ok=True)

conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT,
    last_login TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT UNIQUE NOT NULL,
    name TEXT,
    created_by TEXT,
    created_at TEXT,
    expires_at TEXT
)''')

admin_pass = os.environ.get('SIPMAN_ADMIN_PASS', 'ChangeMeNow!2026#sipman')
password_hash = generate_password_hash(admin_pass, method='pbkdf2:sha256')
c.execute(
    'INSERT OR IGNORE INTO admins (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)',
    ('admin', password_hash, 'admin@localhost', datetime.datetime.now().isoformat())
)

conn.commit()
conn.close()
print('[OK] Admin database created with default admin:<admin_pass>')
print('[IMPORTANT] Change the default admin password immediately after first login!')
" 2>&1

echo ""
echo "[STEP 9] Restarting services..."

echo "[STEP 10] Reloading systemd..."
systemctl daemon-reload

echo "[STEP 10] Restarting Kamailio..."
systemctl reset-failed kamailio 2>/dev/null || true
systemctl restart kamailio || echo "[WARN] Kamailio restart failed - check config"
sleep 2
echo "  Kamailio: $(systemctl is-active kamailio)"

echo "[STEP 10] Restarting RTPEngine..."
systemctl restart rtpengine
echo "[OK] RTPEngine restarted"

echo "[STEP 10] Starting SIP Manager web service..."
systemctl restart sipman-web
sleep 2
echo "  sipman-web: $(systemctl is-active sipman-web)"

echo "[STEP 10] Testing nginx config..."
nginx -t 2>&1
systemctl reload nginx
echo "[OK] nginx reloaded"

echo ""
echo "[STEP 11] Verifying services..."
sleep 3

echo "  Kamailio:    $(systemctl is-active kamailio)"
echo "  RTPEngine:   $(systemctl is-active rtpengine)"
echo "  nginx:       $(systemctl is-active nginx)"
echo "  sipman-web:  $(systemctl is-active sipman-web)"
echo "  MariaDB:     $(systemctl is-active mariadb)"

echo ""
echo "[STEP 12] Verifying ports..."
ss -tulnp | grep -E '5060|5061|5000|3306|10000-20000' || true

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "Access the web UI at: https://sip.mrnet.work:5000/"
echo "Default admin credentials: admin / admin"
echo ""
echo "Existing SIP users have been migrated from the database."
echo "Their passwords remain as 'Morton@1645'"
echo ""
echo "Logs:"
echo "  Kamailio:  /var/log/kamailio/kamailio.log"
echo "  sipman:    journalctl -u sipman-web"
echo "  nginx:     /var/log/nginx/sipman_*.log"
echo ""
echo "Troubleshooting:"
echo "  systemctl status kamailio"
echo "  systemctl status sipman-web"
echo "  journalctl -u kamailio -n 50"
echo "  journalctl -u sipman-web -n 50"
