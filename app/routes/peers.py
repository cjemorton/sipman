"""
Peer sync endpoints — internal API used by other SipMan nodes.
Protected by X-Peer-Secret header, not JWT.
"""

from flask import Blueprint, jsonify, request

from app.auth import peer_auth_required
from app.peers import sync_user, sync_domain, sync_gateway, sync_delete, receive_full_sync

bp = Blueprint('peers', __name__)


@bp.route('/sync/users', methods=['POST', 'PUT'])
@peer_auth_required
def sync_users():
    data = request.get_json(silent=True) or {}
    ok, msg = sync_user(data)
    return jsonify({"synced": ok, "message": msg})


@bp.route('/sync/users', methods=['DELETE'])
@peer_auth_required
def sync_users_delete():
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    domain = data.get('domain')
    if not username or not domain:
        return jsonify({"error": "username and domain required"}), 400
    ok, msg = sync_delete('subscriber', 'username', username)
    return jsonify({"deleted": ok, "message": msg})


@bp.route('/sync/domains', methods=['POST', 'PUT'])
@peer_auth_required
def sync_domains():
    data = request.get_json(silent=True) or {}
    ok, msg = sync_domain(data)
    return jsonify({"synced": ok, "message": msg})


@bp.route('/sync/domains', methods=['DELETE'])
@peer_auth_required
def sync_domains_delete():
    data = request.get_json(silent=True) or {}
    domain = data.get('domain')
    if not domain:
        return jsonify({"error": "domain required"}), 400
    ok, msg = sync_delete('domain', 'domain', domain)
    return jsonify({"deleted": ok, "message": msg})


@bp.route('/sync/gateways', methods=['POST', 'PUT'])
@peer_auth_required
def sync_gateways():
    data = request.get_json(silent=True) or {}
    ok, msg = sync_gateway(data)
    return jsonify({"synced": ok, "message": msg})


@bp.route('/sync/gateways', methods=['DELETE'])
@peer_auth_required
def sync_gateways_delete():
    data = request.get_json(silent=True) or {}
    dest = data.get('destination')
    if not dest:
        return jsonify({"error": "destination required"}), 400
    ok, msg = sync_delete('dispatcher', 'destination', dest)
    return jsonify({"deleted": ok, "message": msg})


@bp.route('/sync/full', methods=['POST'])
@peer_auth_required
def sync_full():
    data = request.get_json(silent=True) or {}
    result = receive_full_sync(data)
    return jsonify(result)
