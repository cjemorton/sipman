"""Authentication routes — login, token validation."""

from flask import Blueprint, jsonify, request, session

from app.auth import generate_jwt, verify_jwt, authenticate_admin
from app.config import Config
from app.database import update_last_login

bp = Blueprint('auth', __name__)


@bp.route('/api/v1/login', methods=['POST'])
def login():
    """Accept JSON or form-encoded login. Return JWT."""
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form

    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    admin = authenticate_admin(username, password)
    if not admin:
        return jsonify({"error": "Invalid credentials"}), 401

    update_last_login(admin['id'])

    token = generate_jwt(username, cluster_id=Config.CLUSTER_ID)
    return jsonify({
        "token": token,
        "expires_in": 86400,
        "cluster_id": Config.CLUSTER_ID,
    })


@bp.route('/api/v1/verify', methods=['POST'])
def verify():
    """Verify a JWT token (used by the Worker to check validity)."""
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:]
    else:
        token = request.get_json(silent=True, force=True) or {}
        token = token.get('token', '')

    payload, err = verify_jwt(token)
    if payload:
        return jsonify({"valid": True, "user": payload.get('user'), "cluster": payload.get('cluster')})
    return jsonify({"valid": False, "error": err}), 401
