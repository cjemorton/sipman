"""Gateway (dispatcher) CRUD + health check endpoints."""

import socket
import time

from flask import Blueprint, jsonify, request

from app.auth import jwt_required
from app.database import db_query, db_execute
from app.peers import replicate_to_peers
from app.kamailio import kamcmd

bp = Blueprint('gateways', __name__)


@bp.route('/api/v1/gateways')
@jwt_required
def list_gateways():
    gws = db_query(
        "SELECT id, setid, destination, description, flags, priority, attrs "
        "FROM dispatcher ORDER BY setid, id"
    )
    return jsonify(gws)


@bp.route('/api/v1/gateways/<int:gw_id>')
@jwt_required
def get_gateway(gw_id):
    rows = db_query(
        "SELECT id, setid, destination, description, flags, attrs "
        "FROM dispatcher WHERE id=%s", (gw_id,)
    )
    if not rows:
        return jsonify({"error": "Gateway not found"}), 404
    return jsonify(rows[0])


@bp.route('/api/v1/gateways', methods=['POST'])
@jwt_required
def create_gateway():
    data = request.get_json(silent=True) or request.form
    setid = data.get('setid', 1)
    destination = (data.get('destination') or '').strip()
    description = data.get('description', '')
    attrs = data.get('attrs', '')
    flags = data.get('flags', 0)

    if not destination:
        return jsonify({"error": "destination required"}), 400

    new_id = db_execute(
        "INSERT INTO dispatcher (setid, destination, flags, description, attrs) "
        "VALUES (%s, %s, %s, %s, %s)",
        (setid, destination, flags, description, attrs)
    )
    if new_id is None:
        return jsonify({"error": "Database error"}), 500

    kamcmd('dispatcher.reload')
    replicate_to_peers('/sync/gateways', 'POST', {
        'setid': setid, 'destination': destination,
        'description': description, 'attrs': attrs, 'flags': flags,
    })
    return jsonify({"id": new_id, "destination": destination}), 201


@bp.route('/api/v1/gateways/<int:gw_id>', methods=['PUT'])
@jwt_required
def update_gateway(gw_id):
    data = request.get_json(silent=True) or request.form
    existing = db_query("SELECT * FROM dispatcher WHERE id=%s", (gw_id,))
    if not existing:
        return jsonify({"error": "Gateway not found"}), 404
    e = existing[0]

    setid = data.get('setid', e['setid'])
    destination = (data.get('destination') or e['destination']).strip()
    description = data.get('description', e.get('description', ''))
    attrs = data.get('attrs', e.get('attrs', ''))
    flags = data.get('flags', e.get('flags', 0))

    db_execute(
        "UPDATE dispatcher SET setid=%s, destination=%s, description=%s, attrs=%s, flags=%s WHERE id=%s",
        (setid, destination, description, attrs, flags, gw_id)
    )
    kamcmd('dispatcher.reload')
    replicate_to_peers('/sync/gateways', 'PUT', {
        'setid': setid, 'destination': destination,
        'description': description, 'attrs': attrs, 'flags': flags,
    })
    return jsonify({"id": gw_id, "updated": True})


@bp.route('/api/v1/gateways/<int:gw_id>', methods=['DELETE'])
@jwt_required
def delete_gateway(gw_id):
    rows = db_query("SELECT destination FROM dispatcher WHERE id=%s", (gw_id,))
    if not rows:
        return jsonify({"error": "Gateway not found"}), 404
    dest = rows[0]['destination']
    db_execute("DELETE FROM dispatcher WHERE id=%s", (gw_id,))
    kamcmd('dispatcher.reload')
    replicate_to_peers('/sync/gateways', 'DELETE', {'destination': dest})
    return jsonify({"deleted": True, "id": gw_id})


@bp.route('/api/v1/gateways/health')
@jwt_required
def gateway_health():
    """Ping all gateways via UDP OPTIONS."""
    gateways = db_query(
        "SELECT id, setid, destination, description, flags "
        "FROM dispatcher ORDER BY setid, id"
    )
    results = []
    for gw in gateways:
        dest = gw['destination']
        # Parse IP:port
        if ':' in dest:
            parts = dest.rsplit(':', 1)
            ip = parts[0].replace('sip:', '')
            try:
                port = int(parts[1])
            except ValueError:
                port = 5060
        else:
            ip = dest.replace('sip:', '')
            port = 5060

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            start = time.time()
            s.sendto(b"OPTIONS SIP/2.0\r\n\r\n", (ip, port))
            elapsed = (time.time() - start) * 1000
            s.close()
            status = "reachable"
            latency = f"{elapsed:.1f}ms"
        except Exception:
            status = "unreachable"
            latency = "N/A"

        results.append({
            'id': gw['id'], 'destination': dest,
            'description': gw.get('description', ''),
            'setid': gw['setid'], 'status': status, 'latency': latency,
        })
    return jsonify(results)
