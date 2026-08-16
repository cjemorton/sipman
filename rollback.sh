#!/bin/bash
set -euo pipefail

######################################################################
# Rollback Script: Restore dSIPRouter setup
# Use this if the new pure-Kamailio setup has issues.
######################################################################

echo "=========================================="
echo "  Rollback: Restore dSIPRouter Setup"
echo "=========================================="
echo ""
echo "WARNING: This will restore the dSIPRouter web UI and config."
echo "The new sipman-web service will be stopped."
echo ""

# Confirm
read -p "Are you sure you want to rollback? (type 'yes' to confirm): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Rollback cancelled."
    exit 0
fi

echo ""
echo "[STEP 1] Restoring Kamailio config..."
# Find the most recent backup
KAM_BACKUP=$(ls -t /etc/kamailio/kamailio.cfg.backup.* 2>/dev/null | head -1)
if [ -n "$KAM_BACKUP" ]; then
    cp "$KAM_BACKUP" /etc/kamailio/kamailio.cfg
    echo "[OK] Restored Kamailio config from $KAM_BACKUP"
else
    echo "[WARN] No Kamailio backup found. Using .bak file..."
    cp /etc/kamailio/kamailio.cfg.bak /etc/kamailio/kamailio.cfg 2>/dev/null || echo "[ERROR] No backup found!"
fi

echo ""
echo "[STEP 2] Restoring nginx config..."
# Restore dSIPRouter nginx config
if [ -f /etc/nginx/sites-available/dsiprouter.conf.backup.* ]; then
    cp /etc/nginx/sites-available/dsiprouter.conf.backup.* /etc/nginx/sites-available/dsiprouter.conf
    ln -sf /etc/nginx/sites-available/dsiprouter.conf /etc/nginx/sites-enabled/dsiprouter.conf
    rm -f /etc/nginx/sites-enabled/sipman.conf
    echo "[OK] Restored dSIPRouter nginx config"
else
    echo "[WARN] No nginx backup found"
fi

echo ""
echo "[STEP 3] Stopping SIP Manager web service..."
systemctl stop sipman-web 2>/dev/null || true
systemctl disable sipman-web 2>/dev/null || true
echo "[OK] SIP Manager stopped"

echo ""
echo "[STEP 4] Restoring dSIPRouter database tables..."
# Look for backup SQL files from migration
BACKUP_SQL=$(ls -t /tmp/sipman_migrate_backup.sql 2>/dev/null | head -1)
if [ -n "$BACKUP_SQL" ]; then
    echo "[INFO] A full DB backup exists at $BACKUP_SQL"
    echo "       To fully restore, run: mysql kamailio < $BACKUP_SQL"
    echo "       This will re-add dSIPRouter-specific tables."
else
    echo "[WARN] No database backup found - dSIPRouter tables may be missing"
fi

echo ""
echo "[STEP 5] Restarting services..."
systemctl restart kamailio
systemctl restart rtpengine
systemctl restart nginx
systemctl start dsiprouter

echo ""
echo "[STEP 6] Verifying services..."
sleep 2
echo "  Kamailio:    $(systemctl is-active kamailio)"
echo "  RTPEngine:   $(systemctl is-active rtpengine)"
echo "  nginx:       $(systemctl is-active nginx)"
echo "  dsiprouter:  $(systemctl is-active dsiprouter)"

echo ""
echo "=========================================="
echo "  Rollback Complete!"
echo "=========================================="
echo "dSIPRouter has been restored."
echo "Access: https://sip.mrnet.work:5000/"
echo "dSIPRouter credentials: admin / see dsip_settings table"
