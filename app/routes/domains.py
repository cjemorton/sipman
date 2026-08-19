"""Domain CRUD endpoints."""

from flask import Blueprint, jsonify, request

from app.auth import jwt_required
from app.config import Config
from app.database import db_query, db_execute
from app.peers import replicate_to_peers
from app.kamailio import kamcmd

bp = Blueprint('domains', __name__)


@bp.route('/api/v1/domains')
@jwt_required
def list_domains():
    domains = db_query(
        "SELECT id, domain, did, last_modified FROM domain ORDER BY domain"
    )
    return jsonify(domains)


@bp.route('/api/v1/domains/<int:domain_id>')
@jwt_required
def get_domain(domain_id):
    rows = db_query("SELECT id, domain, did FROM domain WHERE id=%s", (domain_id,))
    if not rows:
        return jsonify({"error": "Domain not found"}), 404
    return jsonify(rows[0])


@bp.route('/api/v1/domains', methods=['POST'])
@jwt_required
def create_domain():
    data = request.get_json(silent=True) or request.form
    domain = (data.get('domain') or '').strip()
    did = data.get('did') or domain
    if not domain:
        return jsonify({"error": "domain required"}), 400

    dup = db_query("SELECT id FROM domain WHERE domain=%s", (domain,))
    if dup:
        return jsonify({"error": "Domain already exists"}), 409

    new_id = db_execute(
        "INSERT INTO domain (domain, did) VALUES (%s, %s)", (domain, did)
    )
    if new_id is None:
        return jsonify({"error": "Database error"}), 500

    kamcmd('domain.reload')
    replicate_to_peers('/sync/domains', 'POST', {'domain': domain, 'did': did})
    return jsonify({"id": new_id, "domain": domain}), 201


@bp.route('/api/v1/domains/<int:domain_id>', methods=['PUT'])
@jwt_required
def update_domain(domain_id):
    data = request.get_json(silent=True) or request.form
    domain = (data.get('domain') or '').strip()
    did = data.get('did') or domain

    existing = db_query("SELECT * FROM domain WHERE id=%s", (domain_id,))
    if not existing:
        return jsonify({"error": "Domain not found"}), 404

    db_execute(
        "UPDATE domain SET domain=%s, did=%s WHERE id=%s",
        (domain or existing[0]['domain'], did, domain_id)
    )
    kamcmd('domain.reload')
    replicate_to_peers('/sync/domains', 'PUT', {'domain': domain, 'did': did})
    return jsonify({"id": domain_id, "updated": True})


@bp.route('/api/v1/domains/<int:domain_id>', methods=['DELETE'])
@jwt_required
def delete_domain(domain_id):
    rows = db_query("SELECT domain FROM domain WHERE id=%s", (domain_id,))
    if not rows:
        return jsonify({"error": "Domain not found"}), 404

    domain_name = rows[0]['domain']
    db_execute("DELETE FROM domain WHERE id=%s", (domain_id,))
    kamcmd('domain.reload')
    replicate_to_peers('/sync/domains', 'DELETE', {'domain': domain_name})
    return jsonify({"deleted": True, "id": domain_id})
