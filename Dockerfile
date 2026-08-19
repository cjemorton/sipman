# ============================================================
# SipMan Backend — Dockerfile (Optimized)
# Self-contained Kamailio + RTPEngine + MariaDB + Flask API
# Base: Alpine Linux 3.20
#
# Optimizations:
#   - Multi-stage build (Python venv built in builder, copied to final)
#   - Removed nftables, iptables, procps (not needed with RTPEngine userspace)
#   - Replaced mysql-connector-python (25MB) with PyMySQL (1MB)
#   - Reduced image size from ~696MB to ~400-450MB
# ============================================================

# ---- Stage 1: Python builder ----
FROM alpine:3.20 AS builder

RUN apk add --no-cache python3 py3-pip py3-virtualenv

WORKDIR /tmp
COPY requirements.txt .
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ============================================================
# Stage 2: Final image
# ============================================================
FROM alpine:3.20

# ---- Enable the community repository (Kamailio + RTPEngine live here) ----
RUN grep -m1 '/main$' /etc/apk/repositories | sed 's/main/community/' >> /etc/apk/repositories

# ---- Install system packages (trimmed) ----
# Removed vs original:
#   nftables  — RTPEngine uses userspace mode (table=-1), no kernel rules
#   iptables  — Docker handles its own; we don't manage firewall inside container
#   procps    — debug-only, not needed in production
#   py3-pip   — installed in builder stage, not needed in final image
#   py3-virtualenv — using --target=/venv instead
RUN apk add --no-cache \
    kamailio \
    kamailio-db \
    kamailio-mysql \
    kamailio-tls \
    kamailio-extras \
    rtpengine \
    iproute2 \
    mariadb \
    mariadb-client \
    supervisor \
    gettext \
    openssl \
    curl \
    python3 \
    bash \
    && rm -rf /var/cache/apk/*

# ---- Copy Python deps from builder stage ----
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/opt/venv"

# ---- Copy application code ----
WORKDIR /app
COPY app/ /app/app/
COPY wsgi.py /app/wsgi.py

# ---- Copy Docker configs ----
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/supervisord.conf /etc/supervisord.conf
COPY docker/kamailio.cfg.tmpl /etc/kamailio/kamailio.cfg.tmpl
COPY docker/tls.cfg.tmpl /etc/kamailio/tls.cfg.tmpl
COPY docker/dmq_helper.sh /dmq_helper.sh
COPY docker/kamailio-start.sh /kamailio-start.sh
COPY docker/mariadb.cnf /etc/my.cnf.d/sipman.cnf

RUN chmod +x /entrypoint.sh /dmq_helper.sh /kamailio-start.sh

# ---- Create directories & permissions ----
RUN mkdir -p /data /var/run/kamailio /var/run/mariadb \
    /var/log/supervisor /etc/kamailio/tls \
    && chown -R kamailio:kamailio /var/run/kamailio /etc/kamailio \
    && chown -R mysql:mysql /var/lib/mysql /var/run/mariadb

# ---- Default environment ----
ENV CLUSTER_ID=primary \
    CLUSTER_NAME="SIP Manager Cluster" \
    SIP_DOMAIN=sip.mrnet.work \
    SIP_EXTERNAL_IP=127.0.0.1 \
    SIP_PORT=5060 \
    SIPS_PORT=5061 \
    MARIADB_HOST=127.0.0.1 \
    MARIADB_PORT=3306 \
    MARIADB_USER=kamailio \
    MARIADB_PASS=kamailio \
    MARIADB_DB=kamailio \
    RTPENGINE_HOST=127.0.0.1 \
    RTPENGINE_PORT=7722 \
    RTPENGINE_INTERFACE=0.0.0.0 \
    SIPMAN_ADMIN_USER=admin \
    SIPMAN_ADMIN_PASS=ChangeMeNow!2026#sipman \
    SIPMAN_JWT_SECRET= \
    PEER_NODES= \
    PEER_SYNC_SECRET= \
    PEER_SYNC_ENABLED=false

# ---- Expose ports ----
# 5060/udp+tcp = SIP, 5061/tcp = SIPS/TLS, 5000/tcp = API
# With network_mode: host, these are informational only.
EXPOSE 5060/udp 5060/tcp 5061/tcp 5000/tcp

# ---- Volumes ----
VOLUME ["/var/lib/mysql", "/data"]

# ---- Entrypoint ----
ENTRYPOINT ["/entrypoint.sh"]
