"""User (SIP subscriber) CRUD endpoints — full REST API."""

import csv
import io
import hashlib

from flask import Blueprint, jsonify, request, Response

from app.auth import jwt_required
from app.config import Config
from app.database import db_query, db_execute
from app.peers import compute_ha1, replicate_to_peers

bp = Blueprint('users', __name__)


def _ha1(username, domain, password):
    return hashlib.md5(f"{username}:{domain}:{password}".encode()).hexdigest()


@bp.route('/api/v1/users')
@jwt_required
def list_users():
    users = db_query(
        "SELECT id, username, domain, ha1, email_address "
        "FROM subscriber ORDER BY CAST(username AS UNSIGNED)"
    )
    return jsonify(users)


@bp.route('/api/v1/users/<int:user_id>')
@jwt_required
def get_user(user_id):
    users = db_query(
        "SELECT id, username, domain, ha1, email_address "
        "FROM subscriber WHERE id=%s", (user_id,)
    )
    if not users:
        return jsonify({"error": "User not found"}), 404
    return jsonify(users[0])


@bp.route('/api/v1/users', methods=['POST'])
@jwt_required
def create_user():
    data = request.get_json(silent=True) or request.form
    username = (data.get('username') or '').strip()
    domain = (data.get('domain') or Config.SIP_DOMAIN).strip()
    password = data.get('password') or ''
    email = (data.get('email') or data.get('email_address') or '').strip()
    ha1 = data.get('ha1') or (_ha1(username, domain, password) if password else None)

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    # Check duplicate
    dup = db_query("SELECT id FROM subscriber WHERE username=%s AND domain=%s", (username, domain))
    if dup:
        return jsonify({"error": "User already exists"}), 409

    rpid = data.get('rpid', f'extension_{username}')
    new_id = db_execute(
        "INSERT INTO subscriber (username, domain, password, ha1, email_address, rpid) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (username, domain, password, ha1, email, rpid)
    )
    if new_id is None:
        return jsonify({"error": "Database error"}), 500

    # Reload Kamailio's in-memory location cache for this user
    from app.kamailio import kamcmd
    kamcmd('ul.reload')

    # Replicate to peers
    replicate_to_peers('/sync/users', 'POST', {
        'username': username, 'domain': domain, 'password': password,
        'ha1': ha1, 'email': email, 'rpid': rpid,
    })

    return jsonify({"id": new_id, "username": username, "domain": domain}), 201


@bp.route('/api/v1/users/<int:user_id>', methods=['PUT'])
@jwt_required
def update_user(user_id):
    data = request.get_json(silent=True) or request.form
    username = (data.get('username') or '').strip()
    domain = (data.get('domain') or Config.SIP_DOMAIN).strip()
    password = data.get('password') or ''
    email = (data.get('email') or data.get('email_address') or '').strip()

    existing = db_query("SELECT * FROM subscriber WHERE id=%s", (user_id,))
    if not existing:
        return jsonify({"error": "User not found"}), 404
    existing = existing[0]

    ha1 = existing['ha1']
    if password and password != '******':
        ha1 = _ha1(username or existing['username'], domain or existing['domain'], password)

    db_execute(
        "UPDATE subscriber SET username=%s, domain=%s, password=%s, ha1=%s, email_address=%s "
        "WHERE id=%s",
        (username or existing['username'], domain or existing['domain'],
         password or existing.get('password', ''), ha1, email, user_id)
    )

    from app.kamailio import kamcmd
    kamcmd('ul.reload')

    replicate_to_peers('/sync/users', 'PUT', {
        'username': username or existing['username'],
        'domain': domain or existing['domain'],
        'password': password, 'ha1': ha1, 'email': email,
    })

    return jsonify({"id": user_id, "updated": True})


@bp.route('/api/v1/users/<int:user_id>', methods=['DELETE'])
@jwt_required
def delete_user(user_id):
    users = db_query("SELECT username, domain FROM subscriber WHERE id=%s", (user_id,))
    if not users:
        return jsonify({"error": "User not found"}), 404

    username = users[0]['username']
    domain = users[0]['domain']
    db_execute("DELETE FROM subscriber WHERE id=%s", (user_id,))

    from app.kamailio import kamcmd
    kamcmd('ul.reload')

    replicate_to_peers('/sync/users', 'DELETE', {
        'username': username, 'domain': domain,
    })

    return jsonify({"deleted": True, "id": user_id})


@bp.route('/api/v1/users/export')
@jwt_required
def export_users():
    """Export all subscribers as CSV."""
    users = db_query(
        "SELECT username, domain, email_address, ha1 FROM subscriber ORDER BY id"
    )
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['username', 'domain', 'email_address', 'ha1'])
    for u in users:
        w.writerow([u.get('username', ''), u.get('domain', ''),
                     u.get('email_address', ''), u.get('ha1', '')])
    return Response(
        out.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=sip_users.csv'}
    )
