#!/bin/bash
# ============================================================
# SipMan Backend — Container Entrypoint
# Starts MariaDB, Kamailio, RTPEngine, and the Flask API
# ============================================================
set -e

echo "[SIPMAN] Starting SipMan backend container..."
echo "[SIPMAN] Cluster ID: ${CLUSTER_ID:-primary}"
echo "[SIPMAN] SIP Domain: ${SIP_DOMAIN:-sip.mrnet.work}"
echo "[SIPMAN] Peers: ${PEER_NODES:-none}"

# ---- 0. Ensure directories exist ----
mkdir -p /var/run/mariadb /var/run/kamailio /data
chown -R mysql:mysql /var/lib/mysql /var/run/mariadb 2>/dev/null || true
chown -R kamailio:kamailio /var/run/kamailio 2>/dev/null || true

# ---- 0a. Resolve RTPEngine interface (rtpengine rejects 0.0.0.0) ----
# RTPEngine needs a real local IP for its --interface. If the operator left
# RTPENGINE_INTERFACE at the default 0.0.0.0 (or empty), auto-detect the
# container's primary IPv4 address so rtpengine starts out-of-the-box.
if [ -z "${RTPENGINE_INTERFACE:-}" ] || [ "${RTPENGINE_INTERFACE}" = "0.0.0.0" ]; then
    DETECTED_IP=$(hostname -i 2>/dev/null | awk '{print $1}')
    if [ -n "$DETECTED_IP" ]; then
        export RTPENGINE_INTERFACE="$DETECTED_IP"
        echo "[SIPMAN] RTPENGINE_INTERFACE auto-detected: $RTPENGINE_INTERFACE"
    else
        echo "[SIPMAN] WARNING: could not auto-detect IP; rtpengine may fail to start."
    fi
fi

# ---- 1. Initialize MariaDB data dir if empty ----
if [ ! -d "/var/lib/mysql/mysql" ]; then
    echo "[SIPMAN] Initializing MariaDB data directory..."
    mariadb-install-db --user=mysql --datadir=/var/lib/mysql 2>&1 | tail -5
fi

# ---- 2. Start MariaDB (temporary, for schema init) ----
echo "[SIPMAN] Starting MariaDB..."
mariadbd-safe --user=mysql --datadir=/var/lib/mysql --skip-networking=false &
MYSQL_PID=$!
sleep 3

# Wait for MariaDB to be ready
for i in $(seq 1 30); do
    if mariadb-admin ping --silent 2>/dev/null; then
        echo "[SIPMAN] MariaDB is ready."
        break
    fi
    sleep 1
done

# ---- 3. Create Kamailio database & user ----
MYSQL_ROOT_PASS="${MARIADB_ROOT_PASS:-}"
MYSQL_DB="${MARIADB_DB:-kamailio}"
MYSQL_USER="${MARIADB_USER:-kamailio}"
MYSQL_PASS="${MARIADB_PASS:-kamailio}"

# Set root password if provided, else disable remote root
if [ -n "$MYSQL_ROOT_PASS" ]; then
    mariadb -u root -e "ALTER USER 'root'@'localhost' IDENTIFIED BY '${MYSQL_ROOT_PASS}';" 2>/dev/null || true
    ROOT_FLAG="-p${MYSQL_ROOT_PASS}"
else
    ROOT_FLAG=""
fi

# Create database
mariadb -u root $ROOT_FLAG -e "CREATE DATABASE IF NOT EXISTS \`${MYSQL_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;" 2>/dev/null || true

# Create Kamailio user
mariadb -u root $ROOT_FLAG -e "CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'127.0.0.1' IDENTIFIED BY '${MYSQL_PASS}';" 2>/dev/null || true
mariadb -u root $ROOT_FLAG -e "CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'localhost' IDENTIFIED BY '${MYSQL_PASS}';" 2>/dev/null || true
mariadb -u root $ROOT_FLAG -e "GRANT ALL PRIVILEGES ON \`${MYSQL_DB}\`.* TO '${MYSQL_USER}'@'127.0.0.1';" 2>/dev/null || true
mariadb -u root $ROOT_FLAG -e "GRANT ALL PRIVILEGES ON \`${MYSQL_DB}\`.* TO '${MYSQL_USER}'@'localhost';" 2>/dev/null || true
mariadb -u root $ROOT_FLAG -e "FLUSH PRIVILEGES;" 2>/dev/null || true

# ---- 4. Load Kamailio schema ----
if [ ! -f "/var/lib/mysql/.kamailio_schema_loaded" ]; then
    echo "[SIPMAN] Loading Kamailio database schema..."
    # Use kamailio's built-in schema files
    if [ -d "/usr/share/kamailio/mysql" ]; then
        for f in /usr/share/kamailio/mysql/*.sql; do
            mariadb -u root $ROOT_FLAG "${MYSQL_DB}" < "$f" 2>/dev/null || true
        done
        # Also create the SIPMAN-specific tables if not in default schema
        mariadb -u root $ROOT_FLAG "${MYSQL_DB}" <<'SQL'
-- Ensure sip_trace table exists (for call tracing)
CREATE TABLE IF NOT EXISTS sip_trace (
    id INT AUTO_INCREMENT PRIMARY KEY,
    time DATETIME DEFAULT CURRENT_TIMESTAMP,
    method VARCHAR(16),
    src_user VARCHAR(64),
    src_domain VARCHAR(64),
    dst_user VARCHAR(64),
    dst_domain VARCHAR(64),
    status VARCHAR(8),
    callid VARCHAR(128),
    msg TEXT
) ENGINE=InnoDB;
SQL
        touch /var/lib/mysql/.kamailio_schema_loaded
        echo "[SIPMAN] Kamailio schema loaded."
    else
        echo "[SIPMAN] WARNING: Kamailio MySQL schema not found at /usr/share/kamailio/mysql"
    fi
fi

# ---- 5. Render Kamailio config from template ----
echo "[SIPMAN] Rendering kamailio.cfg..."

# Generate DMQ config blocks based on PEER_NODES. dmq_helper.sh prints shell
# variable assignments (WITH_DMQ_DEFINE, DMQ_LISTEN, DMQ_MODULES, DMQ_PARAMS,
# DMQ_ROUTE, DMQ_EVENT_ROUTE, etc.) to stdout; eval them so envsubst can
# substitute the ${DMQ_*} placeholders in the template. When PEER_NODES is
# empty, all of these are set to empty strings (DMQ disabled).
eval "$(bash /dmq_helper.sh)"
export WITH_DMQ_DEFINE DMQ_CONFIG DMQ_LISTEN DMQ_MODULES DMQ_PARAMS \
       DMQ_ROUTE DMQ_EVENT_ROUTE DMQ_USRLOC_PARAMS

# IMPORTANT: pass an explicit SHELL-FORMAT variable list to envsubst so it ONLY
# substitutes these env vars and leaves Kamailio pseudo-variables ($du, $rU,
# $ci, $rm, $rs, etc.) untouched. A bare `envsubst` would blank every $foo.
KAMAILIO_ENVVARS='${CLUSTER_ID} ${DMQ_CONFIG} ${DMQ_EVENT_ROUTE} ${DMQ_LISTEN} ${DMQ_MODULES} ${DMQ_PARAMS} ${DMQ_ROUTE} ${DMQ_USRLOC_PARAMS} ${WITH_DMQ_DEFINE} ${MARIADB_DB} ${MARIADB_PASS} ${MARIADB_USER} ${RTPENGINE_HOST} ${RTPENGINE_PORT} ${SIPS_PORT} ${SIP_DOMAIN} ${SIP_EXTERNAL_IP} ${SIP_PORT}'
envsubst "$KAMAILIO_ENVVARS" < /etc/kamailio/kamailio.cfg.tmpl > /etc/kamailio/kamailio.cfg
envsubst < /etc/kamailio/tls.cfg.tmpl > /etc/kamailio/tls.cfg 2>/dev/null || true

# ---- 6. Copy MariaDB config (memory-optimized) ----
if [ -f /etc/my.cnf.d/sipman.cnf ]; then
    echo "[SIPMAN] MariaDB config already in place."
else
    echo "[SIPMAN] WARNING: sipman.cnf not found — MariaDB may use default (high) memory settings."
fi

# ---- 6a. Stop temporary MariaDB (supervisord will manage it) ----
echo "[SIPMAN] Stopping temporary MariaDB..."
# Use a clean shutdown so the mariadbd child fully exits; a bare `kill` of
# mariadbd-safe leaves the mariadbd daemon running, which makes the supervised
# instance fail with "A mysqld process already exists".
mariadb-admin shutdown 2>/dev/null || kill $MYSQL_PID 2>/dev/null || true
# Wait until the server is actually down
for i in $(seq 1 15); do
    if ! mariadb-admin ping 2>/dev/null | grep -qi "alive"; then
        break
    fi
    sleep 1
done
# Force-kill any straggler just in case
pkill -f "mariadbd.*--datadir=/var/lib/mysql" 2>/dev/null || true
sleep 1

# ---- 7. Generate self-signed TLS cert if not present ----
if [ ! -f /etc/kamailio/tls/kamailio.crt ]; then
    echo "[SIPMAN] Generating self-signed TLS certificate..."
    mkdir -p /etc/kamailio/tls
    openssl req -x509 -newkey rsa:2048 -keyout /etc/kamailio/tls/kamailio.key \
        -out /etc/kamailio/tls/kamailio.crt -days 3650 -nodes \
        -subj "/CN=${SIP_DOMAIN:-sip.mrnet.work}" 2>/dev/null
fi

# ---- 8. Start supervisord (manages all processes) ----
echo "[SIPMAN] Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisord.conf
