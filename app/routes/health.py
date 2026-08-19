"""Health & readiness endpoints (no auth)."""

from flask import Blueprint, jsonify
from app.database import check_mariadb
from app.kamailio import system_status, check_rtpengine, kamcmd_json

bp = Blueprint('health', __name__)


@bp.route('/health')
@bp.route('/api/v1/health')
def health():
    """Lightweight health check — no auth required."""
    db_ok, db_msg = check_mariadb()
    return jsonify({
        'status': 'ok' if db_ok else 'error',
        'database': 'connected' if db_ok else db_msg,
    })


@bp.route('/api/v1/health/detailed')
def health_detailed():
    """Full health with all service checks."""
    checks = system_status()
    details = {}
    db_ok, db_msg = check_mariadb()
    checks['database'] = db_ok
    details['database'] = db_msg
    kam = kamcmd_json('core.info')
    details['kamailio'] = str(kam)[:200]
    rtp_ok, rtp_msg = check_rtpengine()
    details['rtpengine'] = rtp_msg
    overall = all(checks.values())
    return jsonify({
        'status': 'healthy' if overall else 'degraded',
        'checks': checks,
        'details': details,
    }), 200 if overall else 503
