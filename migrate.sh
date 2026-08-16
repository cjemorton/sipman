#!/bin/bash
set -euo pipefail

######################################################################
# Migration script: Extract data from dSIPRouter database
# This script runs BEFORE the new Kamailio config is deployed.
# It preserves users, domains, and dispatcher gateways.
######################################################################

echo "=========================================="
echo "  Data Migration Script"
echo "  (Pre-deployment - extracts from existing DB)"
echo "=========================================="

DB_NAME="kamailio"
BACKUP_FILE="/tmp/sipman_migrate_backup.sql"

echo ""
echo "[STEP 1] Backing up entire database..."
mysqldump $DB_NAME > $BACKUP_FILE
echo "[OK] Backup saved to $BACKUP_FILE"

echo ""
echo "[STEP 2] Extracting existing SIP users..."
mysql -u root -e "SELECT username, domain, ha1, password, email_address, rpid FROM kamailio.subscriber WHERE domain='sip.mrnet.work';" > /tmp/sipman_migrate_users.txt 2>/dev/null
echo "[OK] Users extracted to /tmp/sipman_migrate_users.txt"
echo ""
cat /tmp/sipman_migrate_users.txt | column -t -R 1,2,3,5,6

echo ""
echo "[STEP 3] Extracting domains..."
mysql -u root -e "SELECT domain, did, last_modified FROM kamailio.domain;" > /tmp/sipman_migrate_domains.txt 2>/dev/null
echo "[OK] Domains extracted"
cat /tmp/sipman_migrate_domains.txt | column -t

echo ""
echo "[STEP 4] Extracting dispatcher gateways..."
mysql -u root -e "SELECT setid, destination, description, flags, attrs FROM kamailio.dispatcher ORDER BY setid, id;" > /tmp/sipman_migrate_gateways.txt 2>/dev/null
echo "[OK] Gateways extracted"
echo "Total gateways: $(wc -l < /tmp/sipman_migrate_gateways.txt)"

echo ""
echo "[STEP 5] Checking kamailio_user permissions..."
# Verify the kamailio DB user can access the subscriber table
mysql -u kamailio -pkamailiorw -e "SELECT count(*) FROM kamailio.subscriber;" kamailio 2>&1 || echo "[WARN] kamailio user may need password update"

echo ""
echo "[STEP 6] Dropping dSIPRouter-specific tables..."
# Drop tables that are specific to dSIPRouter and won't be used
# by the clean Kamailio config
mysql -u root $DB_NAME -e "
DROP TABLE IF EXISTS
    dsip_agent,
    dsip_agent_instruction,
    dsip_call_settings,
    dsip_call_settings_h,
    dsip_cdrinfo,
    dsip_certificates,
    dsip_dnid_enrich_lnp,
    dsip_dnid_lnp_mapping,
    dsip_domain_mapping,
    dsip_endpoint_lease,
    dsip_failfwd,
    dsip_gw2gwgroup,
    dsip_gwgroup2lb,
    dsip_hardfwd,
    dsip_lcr,
    dsip_maintmode,
    dsip_multidomain_mapping,
    dsip_notification,
    dsip_number,
    dsip_prefix_mapping,
    dsip_settings,
    dsip_user;
" 2>&1
echo "[OK] dSIPRouter-specific tables dropped"

echo ""
echo "[STEP 7] Verifying standard Kamailio tables remain..."
mysql -u root -e "SHOW TABLES FROM $DB_NAME;" | grep -E '^(subscriber|location|domain|dispatcher|acc|aliases|version|usr_preferences|domain_attrs|location_attrs)$'

echo ""
echo "[STEP 8] Done. Data is ready for new config."
echo "All user credentials, domains, and gateways have been preserved."
echo "The new Kamailio config will use the same database."
