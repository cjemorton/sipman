"""
Central configuration — all values come from environment variables.
No hardcoded secrets, IPs, or passwords.
"""

import os
import secrets


def _env_bool(key, default=False):
    v = os.environ.get(key, '').strip().lower()
    if v in ('1', 'true', 'yes', 'on'):
        return True
    if v in ('0', 'false', 'no', 'off'):
        return False
    return default


class Config:
    # ---- Flask ----
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))

    # ---- Admin (first-run default) ----
    ADMIN_USERNAME = os.environ.get('SIPMAN_ADMIN_USER', 'admin')
    ADMIN_PASSWORD = os.environ.get('SIPMAN_ADMIN_PASS', 'ChangeMeNow!2026#sipman')

    # ---- JWT ----
    JWT_SECRET = os.environ.get('SIPMAN_JWT_SECRET', SECRET_KEY)

    # ---- MariaDB (Kamailio data) ----
    MARIADB_HOST = os.environ.get('MARIADB_HOST', '127.0.0.1')
    MARIADB_PORT = int(os.environ.get('MARIADB_PORT', '3306'))
    MARIADB_USER = os.environ.get('MARIADB_USER', 'kamailio')
    MARIADB_PASS = os.environ.get('MARIADB_PASS', 'kamailio')
    MARIADB_DB = os.environ.get('MARIADB_DB', 'kamailio')
    DB_CONNECTION_TIMEOUT = int(os.environ.get('DB_CONNECTION_TIMEOUT', '10'))
    DB_RETRY_ATTEMPTS = int(os.environ.get('DB_RETRY_ATTEMPTS', '3'))

    # ---- SQLite (admin users / tokens / settings) ----
    ADMIN_DB_PATH = os.environ.get('SIPMAN_DB_PATH', '/data/sipman.db')

    # ---- Kamailio control socket ----
    KAMCMD_SOCKET = os.environ.get('KAMCMD_SOCKET', '/var/run/kamailio/kamailio_ctl')
    KAMCMD_CMD = os.environ.get('KAMCMD_CMD', '/usr/sbin/kamcmd')

    # ---- RTPEngine ----
    RTPENGINE_HOST = os.environ.get('RTPENGINE_HOST', '127.0.0.1')
    RTPENGINE_PORT = int(os.environ.get('RTPENGINE_PORT', '7722'))

    # ---- Cluster identity ----
    CLUSTER_ID = os.environ.get('CLUSTER_ID', 'primary')
    CLUSTER_NAME = os.environ.get('CLUSTER_NAME', 'SIP Manager Cluster')
    CLUSTER_BACKEND_URL = os.environ.get('CLUSTER_BACKEND_URL', '')

    # ---- SIP domain ----
    SIP_DOMAIN = os.environ.get('SIP_DOMAIN', 'sip.mrnet.work')

    # ---- Peer nodes (comma-separated URLs for API-level sync) ----
    # e.g. "http://10.0.0.2:5000,http://10.0.0.3:5000"
    PEER_NODES = [
        u.strip() for u in os.environ.get('PEER_NODES', '').split(',')
        if u.strip()
    ]

    # ---- Peer sync shared secret (must match across all peers) ----
    PEER_SYNC_SECRET = os.environ.get('PEER_SYNC_SECRET', '')

    # ---- Enable/disable peer sync (auto-enabled if PEER_NODES set) ----
    PEER_SYNC_ENABLED = _env_bool('PEER_SYNC_ENABLED', bool(PEER_NODES))

    # ---- Allow CORS from the worker origin ----
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*')

    @classmethod
    def reload(cls):
        """Re-read env vars (useful for testing)."""
        return Config()
