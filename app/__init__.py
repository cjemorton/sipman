"""
SipMan Backend - Flask Application Factory
Pure REST API for managing Kamailio SIP endpoints.

No HTML templates — the frontend is a Cloudflare Worker that talks
to this API via JSON over HTTP.
"""

import os
import sys

from flask import Flask

from app.config import Config
from app.database import init_admin_db, check_mariadb


def create_app(config_class=Config):
    """Application factory pattern."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # ---- Initialize SQLite admin DB (auth tokens, settings) ----
    init_admin_db()

    # ---- Register Blueprints (route modules) ----
    from app.routes.health import bp as health_bp
    from app.routes.auth import bp as auth_bp
    from app.routes.users import bp as users_bp
    from app.routes.domains import bp as domains_bp
    from app.routes.gateways import bp as gateways_bp
    from app.routes.cluster import bp as cluster_bp
    from app.routes.statistics import bp as stats_bp
    from app.routes.profile import bp as profile_bp
    from app.routes.peers import bp as peers_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(domains_bp)
    app.register_blueprint(gateways_bp)
    app.register_blueprint(cluster_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(peers_bp)

    # ---- Startup info ----
    db_ok, db_msg = check_mariadb()
    if db_ok:
        print(f"[SIPMAN] MariaDB connection OK — {db_msg}", flush=True)
    else:
        print(f"[SIPMAN] WARNING: MariaDB not accessible — {db_msg}", file=sys.stderr, flush=True)

    print(f"[SIPMAN] Cluster: {config_class.CLUSTER_ID} ({config_class.CLUSTER_NAME})", flush=True)
    print(f"[SIPMAN] Peers: {config_class.PEER_NODES or 'none'}", flush=True)

    return app


# For gunicorn / wsgi
app = create_app()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
