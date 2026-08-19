"""Cluster identification & registry endpoints."""

import datetime
from flask import Blueprint, jsonify, request

from app.auth import jwt_required
from app.config import Config
from app.database import get_setting, set_setting, db_query, _admin_conn
from app.kamailio import system_status
from app.peers import full_sync_to_peers
import json

bp = Blueprint('cluster', __name__)


@bp.route('/api/v1/cluster')
@jwt_required
def cluster_info():
    """Return this node's identity, status, and DB connectivity."""
    return jsonify({
        'cluster_id': Config.CLUSTER_ID,
        'cluster_name': Config.CLUSTER_NAME,
        'backend_url': Config.CLUSTER_BACKEND_URL or request.host_url.rstrip('/'),
        'status': system_status(),
        'db_connected': system_status()['db_connected'],
        'sip_domain': Config.SIP_DOMAIN,
        'peers': Config.PEER_NODES,
        'peer_sync_enabled': Config.PEER_SYNC_ENABLED,
        'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
    })


@bp.route('/api/v1/clusters')
@jwt_required
def list_clusters():
    """List all known clusters (self + peers registered in settings)."""
    registry = get_setting('clusters')
    if registry:
        try:
            return jsonify(json.loads(registry))
        except (json.JSONDecodeError, TypeError):
            pass

    # Default: just this cluster
    return jsonify([{
        'id': Config.CLUSTER_ID,
        'name': Config.CLUSTER_NAME,
        'backend_url': Config.CLUSTER_BACKEND_URL or request.host_url.rstrip('/'),
        'type': 'primary',
    }])


@bp.route('/api/v1/clusters', methods=['POST'])
@jwt_required
def register_cluster():
    """Register a new cluster in the registry (stored in SQLite settings)."""
    data = request.get_json(silent=True) or request.form
    cid = data.get('id') or data.get('cluster_id')
    name = data.get('name') or data.get('cluster_name')
    url = data.get('backend_url') or data.get('url')
    if not cid:
        return jsonify({"error": "cluster id required"}), 400

    registry = []
    raw = get_setting('clusters')
    if raw:
        try:
            registry = json.loads(raw)
        except Exception:
            registry = []

    # Add or update
    found = False
    for c in registry:
        if c.get('id') == cid:
            c['name'] = name or c.get('name')
            c['backend_url'] = url or c.get('backend_url')
            found = True
            break
    if not found:
        registry.append({
            'id': cid, 'name': name, 'backend_url': url, 'type': 'secondary'
        })

    set_setting('clusters', json.dumps(registry))
    return jsonify(registry)


@bp.route('/api/v1/cluster/sync', methods=['POST'])
@jwt_required
def trigger_full_sync():
    """Manually trigger a full data push to all peers."""
    result = full_sync_to_peers()
    return jsonify(result)
