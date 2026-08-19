# ============================================================
# SipMan Backend — Dockerfile
# Self-contained Kamailio + RTPEngine + MariaDB + Flask API
# Base: Alpine Linux 3.20
#
# Kamailio and RTPEngine are NOT available as RPMs for EL9/Rocky
# (EPEL 9 has no Kamailio; rpm.kamailio.org only covers CentOS <=7).
# Alpine's community repo ships prebuilt Kamailio + RTPEngine for
# both x86_64 and aarch64, so we fall back to Alpine per the task spec.
# ============================================================

FROM alpine:3.20

# ---- Enable the community repository (Kamailio + RTPEngine live here) ----
# The default alpine image ships only the "main" repo. We append a matching
# "community" line derived from the existing main line.
RUN grep -m1 '/main$' /etc/apk/repositories | sed 's/main/community/' >> /etc/apk/repositories

# ---- Install system packages ----
# Alpine Kamailio is split into sub-packages; module -> package mapping:
#   kamailio (core)            : kex, corex, tm, sl, rr, path, pv, maxfwd,
#                               usrloc, registrar, textops, siputils, xlog,
#                               sanity, ctl, cfg_rpc, acc, xhttp, jsonrpcs,
#                               ipops, sdpops, nathelper, htable, pike,
#                               rtpengine.so
#   kamailio-mysql             : db_mysql.so
#   kamailio-db                : dispatcher, domain, dialog, auth_db, permissions
#   kamailio-tls               : tls.so
#   kamailio-extras            : dmq.so
#   rtpengine (separate pkg)   : /usr/bin/rtpengine daemon
# MariaDB Alpine package creates the "mysql" user automatically.
RUN apk add --no-cache \
    kamailio \
    kamailio-db \
    kamailio-mysql \
    kamailio-tls \
    kamailio-extras \
    rtpengine \
    nftables \
    iptables \
    iproute2 \
    mariadb \
    mariadb-client \
    supervisor \
    gettext \
    openssl \
    curl \
    procps \
    python3 \
    py3-pip \
    py3-virtualenv \
    bash \
    && rm -rf /var/cache/apk/*

# ---- Create Python venv & install Flask deps ----
# Alpine's python3 stdlib includes venv; py3-virtualenv ensures the module.
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# ---- Copy application code ----
WORKDIR /app
COPY app/ /app/app/
COPY wsgi.py /app/wsgi.py
COPY requirements.txt /app/requirements.txt

# ---- Copy Docker configs ----
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/supervisord.conf /etc/supervisord.conf
COPY docker/kamailio.cfg.tmpl /etc/kamailio/kamailio.cfg.tmpl
COPY docker/tls.cfg.tmpl /etc/kamailio/tls.cfg.tmpl
COPY docker/dmq_helper.sh /dmq_helper.sh

RUN chmod +x /entrypoint.sh /dmq_helper.sh

# ---- Create directories & permissions ----
# Alpine auto-assigns distinct uids when both kamailio and mariadb packages
# are installed (kamailio=100, mysql=101 when kamailio installs first).
# chown by name so ownership is unambiguous regardless of uid numbering.
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
