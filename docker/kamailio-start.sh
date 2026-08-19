#!/bin/bash
# ============================================================
# Kamailio startup wrapper — waits for MariaDB to be ready
# before launching kamailio. Prevents the race condition where
# kamailio starts before MariaDB accepts TCP connections.
# ============================================================
set -e

MARIADB_HOST="${MARIADB_HOST:-127.0.0.1}"
MARIADB_PORT="${MARIADB_PORT:-3306}"
MARIADB_USER="${MARIADB_USER:-kamailio}"
MARIADB_PASS="${MARIADB_PASS:-kamailio}"
MAX_WAIT=60

echo "[SIPMAN] Kamailio wrapper: waiting for MariaDB at ${MARIADB_HOST}:${MARIADB_PORT}..."

for i in $(seq 1 $MAX_WAIT); do
    if mariadb -h "$MARIADB_HOST" -P "$MARIADB_PORT" -u "$MARIADB_USER" -p"$MARIADB_PASS" \
        -e "SELECT 1;" >/dev/null 2>&1; then
        echo "[SIPMAN] MariaDB is ready (after ${i}s). Starting Kamailio..."
        exec /usr/sbin/kamailio -f /etc/kamailio/kamailio.cfg -DD -m 64 -M 16
    fi
    sleep 1
done

echo "[SIPMAN] ERROR: MariaDB not ready after ${MAX_WAIT}s. Starting Kamailio anyway (will retry DB connection)."
exec /usr/sbin/kamailio -f /etc/kamailio/kamailio.cfg -DD -m 64 -M 16
