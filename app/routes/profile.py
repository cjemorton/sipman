"""Admin profile (password change) endpoints."""

from flask import Blueprint, jsonify, request, session

from app.auth import jwt_required
from app.database import get_admin, update_admin_password, _admin_conn
from werkzeug.security import check_password_hash, generate_password_hash

bp = Blueprint('profile', __name__)


@bp.route('/api/v1/profile')
@jwt_required
def get_profile():
    """Return the current admin's profile (from JWT user)."""
    user = getattr(request, 'current_user', None) or session.get('username')
    if not user:
        return jsonify({"error": "No user context"}), 400
    admin = get_admin(user)
    if not admin:
        return jsonify({"error": "User not found"}), 404
    return jsonify({
        'username': admin['username'],
        'email': admin['email'],
        'last_login': admin['last_login'],
    })


@bp.route('/api/v1/profile', methods=['PUT'])
@jwt_required
def update_profile():
    """Change admin password."""
    data = request.get_json(silent=True) or request.form
    current_password = data.get('current_password', '')
    new_password = data.get('password') or data.get('new_password', '')

    if not current_password or not new_password:
        return jsonify({"error": "current_password and password required"}), 400

    user = getattr(request, 'current_user', None) or session.get('username')
    admin = get_admin(user)
    if not admin:
        return jsonify({"error": "User not found"}), 404

    if not check_password_hash(admin['password_hash'], current_password):
        return jsonify({"error": "Current password is incorrect"}), 403

    update_admin_password(admin['id'], generate_password_hash(new_password, method='pbkdf2:sha256'))
    return jsonify({"updated": True})
