"""Statistics & monitoring endpoints."""

from flask import Blueprint, jsonify

from app.auth import jwt_required
from app.database import db_query
from app.kamailio import kamcmd_json, system_status

bp = Blueprint('statistics', __name__)


@bp.route('/api/v1/statistics')
@jwt_required
def statistics():
    stats = {}

    # User count
    users = db_query("SELECT COUNT(*) as count FROM subscriber")
    stats['user_count'] = users[0]['count'] if users else 0

    # Active registrations
    regs = db_query("SELECT COUNT(*) as count FROM location WHERE expires > NOW()")
    stats['registered_devices'] = regs[0]['count'] if regs else 0

    # Recent registrations
    stats['recent_registrations'] = db_query(
        "SELECT username, domain, contact, expires, user_agent "
        "FROM location ORDER BY last_modified DESC LIMIT 10"
    )

    # Active calls (dialog list)
    dialogs = kamcmd_json('dlg.list')
    if isinstance(dialogs, dict) and 'dialog' in dialogs:
        stats['active_calls'] = len(dialogs['dialog'])
    else:
        stats['active_calls'] = 0

    # Recent CDRs
    stats['recent_cdrs'] = db_query(
        "SELECT time, src_user, src_domain, dst_user, dst_domain, sip_code, sip_reason "
        "FROM acc WHERE method = 'INVITE' ORDER BY time DESC LIMIT 20"
    )

    return jsonify(stats)


@bp.route('/api/v1/monitoring')
@jwt_required
def monitoring():
    """Detailed monitoring data."""
    registrations = db_query(
        "SELECT username, domain, contact, expires, user_agent, socket "
        "FROM location ORDER BY username"
    )
    dialogs = kamcmd_json('dlg.list')
    if isinstance(dialogs, dict) and 'dialog' in dialogs:
        active_dialogs = dialogs['dialog']
    else:
        active_dialogs = []

    recent_calls = db_query(
        "SELECT time, src_user, src_domain, dst_user, dst_domain, sip_code, sip_reason "
        "FROM acc WHERE method = 'INVITE' ORDER BY time DESC LIMIT 50"
    )

    return jsonify({
        'registrations': registrations,
        'active_dialogs': active_dialogs,
        'recent_calls': recent_calls,
        'system_status': system_status(),
    })
