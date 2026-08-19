# ============================================================
# SipMan Backend — Dockerfile
# Self-contained Kamailio + RTPEngine + MariaDB + Flask API
# ============================================================

FROM debian:12-slim

# ---- Avoid interactive prompts ----
ENV DEBIAN_FRONTEND=noninteractive

# ---- Install system packages ----
# NOTE: No inline comments inside RUN continuation blocks — BuildKit breaks on them.
RUN apt-get update && apt-get install -y --no-install-recommends \
    kamailio \
    kamailio-mysql-modules \
    kamailio-tls-modules \
    kamailio-rtpengine-modules \
    kamailio-dispatcher-modules \
    kamailio-extra-modules \
    kamailio-dmq-modules \
    kamailio-utils-modules \
    rtpengine \
    mariadb-server \
    mariadb-client \
    supervisor \
    gettext-base \
    openssl \
    curl \
    procps \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# ---- Create Python venv & install Flask deps ----
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ---- Copy application code ----
WORKDIR /app
COPY app/ /app/app/
COPY wsgi.py /app/wsgi.py
COPY requirements.txt /app/requirements.txt

# ---- Copy Docker configs ----
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/kamailio.cfg.tmpl /etc/kamailio/kamailio.cfg.tmpl
COPY docker/tls.cfg.tmpl /etc/kamailio/tls.cfg.tmpl
COPY docker/dmq_helper.sh /dmq_helper.sh

RUN chmod +x /entrypoint.sh /dmq_helper.sh

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
# 5060/udp+tcp = SIP, 5061/tcp = SIPS/TLS, 5000/tcp = API, 7722/udp = RTPEngine control
EXPOSE 5060/udp 5060/tcp 5061/tcp 5000/tcp 7722/udp

# ---- Volumes ----
VOLUME ["/var/lib/mysql", "/data"]

# ---- Entrypoint ----
ENTRYPOINT ["/entrypoint.sh"]
