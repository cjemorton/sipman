"""
Authentication: JWT + API-token + session fallback.
Decorators used by all route blueprints.
"""

import datetime

import jwt as pyjwt
from flask import request, jsonify, session
from werkzeug.security import check_password_hash
from functools import wraps

from app.config import Config
from app.database import get_admin, validate_api_token


def generate_jwt(user, cluster_id=None):
    """Issue a JWT token (24h expiry)."""
    now = datetime.datetime.utcnow()
    payload = {
        'user': user,
        'cluster': cluster_id or Config.CLUSTER_ID,
        'exp': now + datetime.timedelta(hours=24),
        'iat': now,
    }
    return pyjwt.encode(payload, Config.JWT_SECRET, algorithm='HS256')


def verify_jwt(token):
    """Return (payload, None) or (None, error)."""
    try:
        return pyjwt.decode(token, Config.JWT_SECRET, algorithms=['HS256']), None
    except pyjwt.ExpiredSignatureError:
        return None, "Token expired"
    except pyjwt.InvalidTokenError as e:
        return None, str(e)


# ---- Decorators -------------------------------------------------------

def jwt_required(f):
    """
    Accept (in priority order):
      1. Bearer JWT (Worker frontend)
      2. Raw API token (programmatic)
      3. Flask session (direct/local)
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        token = None

        # 1. JWT Bearer
        if auth.startswith('Bearer '):
            token = auth[7:]
            payload, err = verify_jwt(token)
            if payload:
                request.current_user = payload.get('user', 'worker')
                request.current_cluster = payload.get('cluster', 'unknown')
                return f(*args, **kwargs)
            return jsonify({"error": f"Invalid JWT: {err}"}), 401

        # 2. Raw API token
        if auth:
            if validate_api_token(auth):
                return f(*args, **kwargs)

        # 3. Session
        if 'user_id' in session:
            return f(*args, **kwargs)

        return jsonify({"error": "Authentication required"}), 401
    return decorated


def peer_auth_required(f):
    """Authenticate peer-to-peer sync requests via shared secret."""
    @wraps(f)
    def decorated(*args, **kwargs):
        secret = request.headers.get('X-Peer-Secret', '')
        if not Config.PEER_SYNC_SECRET:
            return jsonify({"error": "Peer sync not configured"}), 503
        if secret != Config.PEER_SYNC_SECRET:
            return jsonify({"error": "Invalid peer secret"}), 403
        return f(*args, **kwargs)
    return decorated


def authenticate_admin(username, password):
    """Return admin row dict if credentials match, else None."""
    admin = get_admin(username)
    if admin and check_password_hash(admin['password_hash'], password):
        return admin
    return None
