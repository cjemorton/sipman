#!/bin/bash
# ============================================================
# DMQ Config Helper
# Renders DMQ-related kamailio.cfg sections based on PEER_NODES
# Called by entrypoint.sh before envsubst
# ============================================================

# This script generates the DMQ module blocks for kamailio.cfg
# It's invoked by entrypoint.sh and the output is sourced into the template.

PEER_NODES="${PEER_NODES:-}"

if [ -z "$PEER_NODES" ]; then
    # No peers — output empty strings for all DMQ placeholders
    cat <<'EMPTY'
WITH_DMQ_DEFINE=""
DMQ_CONFIG=""
DMQ_LISTEN=""
DMQ_MODULES=""
DMQ_PARAMS=""
DMQ_USRLOC_PARAMS=""
DMQ_ROUTE=""
DMQ_EVENT_ROUTE=""
EMPTY
else
    # Build DMQ peer list — Kamailio DMQ module needs "sip:host:port" format
    DMQ_PEERS=""
    IFS=',' read -ra PEERS <<< "$PEER_NODES"
    for peer in "${PEERS[@]}"; do
        peer=$(echo "$peer" | xargs)
        # Extract host:port from URL (e.g. http://10.0.0.2:5000 → 10.0.0.2)
        host=$(echo "$peer" | sed 's|.*://||' | sed 's|:.*||')
        if [ -n "$host" ]; then
            if [ -n "$DMQ_PEERS" ]; then
                DMQ_PEERS="$DMQ_PEERS,"
            fi
            DMQ_PEERS="$DMQ_PEERS\"sip:$host:${SIP_PORT:-5060}\""
        fi
    done

    cat <<DMQ_ENABLED
WITH_DMQ_DEFINE="#!define WITH_DMQ"
DMQ_CONFIG="# DMQ peer nodes (comma-separated)"
DMQ_LISTEN="listen = tcp:0.0.0.0:5060 advertise EXTERNAL_IP_ADDR:5060"
DMQ_MODULES='loadmodule "dmq.so"
loadmodule "dmqusrloc.so"'
DMQ_PARAMS='modparam("dmq", "server_address", "sip:${SIP_DOMAIN}:${SIP_PORT:-5060}")
modparam("dmq", "notification_address", "sip:${SIP_DOMAIN}:${SIP_PORT:-5060}")
modparam("dmq", "num_workers", 4)
modparam("dmqusrloc", "enable", 1)'
DMQ_USRLOC_PARAMS="modparam(\"usrloc\", \"db_use_ruri\", 1)"
DMQ_ROUTE="if (\$rm == \"KDMQ\") { dmq_handle_message(); exit; }"
DMQ_EVENT_ROUTE='event_route[dmq:mod-init] {
    xlog("L_WARN", "DMQ module initialized for cluster ${CLUSTER_ID}\n");
}'
DMQ_ENABLED
fi
