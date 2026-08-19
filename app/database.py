"""
Database layer.
- SQLite for admin users, API tokens, settings, peer registry.
- MariaDB (via PyMySQL) for Kamailio's data tables.
"""

import os
import time
import sqlite3
import datetime
import sys

from werkzeug.security import generate_password_hash
from flask import current_app
import pymysql

from app.config import Config


# ============================================================
# SQLite — admin DB
# ============================================================

def _admin_conn():
    path = Config.ADMIN_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_admin_db():
    """Create admin tables and seed the default admin user."""
    conn = _admin_conn()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email       TEXT,
            is_active   INTEGER DEFAULT 1,
            created_at  TEXT,
            last_login  TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS api_tokens (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            token      TEXT UNIQUE NOT NULL,
            name       TEXT,
            created_by TEXT,
            created_at TEXT,
            expires_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS peers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            url        TEXT UNIQUE NOT NULL,
            cluster_id TEXT,
            last_seen  TEXT,
            is_active  INTEGER DEFAULT 1
        )
    ''')
    conn.commit()

    # Seed default admin (INSERT OR IGNORE handles race conditions)
    c.execute(
        "INSERT OR IGNORE INTO admins (username, password_hash, email, created_at) "
        "VALUES (?, ?, ?, ?)",
        (Config.ADMIN_USERNAME,
         generate_password_hash(Config.ADMIN_PASSWORD, method='pbkdf2:sha256'),
         'admin@localhost',
         datetime.datetime.now().isoformat())
    )
    conn.commit()

    # Seed peer nodes from config
    for url in Config.PEER_NODES:
        c.execute(
            "INSERT OR IGNORE INTO peers (url, cluster_id, last_seen, is_active) "
            "VALUES (?, ?, ?, 1)",
            (url, 'unknown', None)
        )
    conn.commit()

    conn.close()
    print(f"[SIPMAN] Admin DB ready at {Config.ADMIN_DB_PATH}", flush=True)


def get_admin(username):
    conn = _admin_conn()
    row = conn.execute(
        "SELECT * FROM admins WHERE username = ? AND is_active = 1", (username,)
    ).fetchone()
    conn.close()
    return row


def update_admin_password(admin_id, password_hash):
    conn = _admin_conn()
    conn.execute(
        "UPDATE admins SET password_hash = ? WHERE id = ?",
        (password_hash, admin_id)
    )
    conn.commit()
    conn.close()


def update_last_login(admin_id):
    conn = _admin_conn()
    conn.execute(
        "UPDATE admins SET last_login = ? WHERE id = ?",
        (datetime.datetime.now().isoformat(), admin_id)
    )
    conn.commit()
    conn.close()


# ============================================================
# SQLite — settings helpers
# ============================================================

def get_setting(key, default=None):
    conn = _admin_conn()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(key, value):
    conn = _admin_conn()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()


# ============================================================
# SQLite — API tokens
# ============================================================

def validate_api_token(token):
    conn = _admin_conn()
    row = conn.execute(
        "SELECT * FROM api_tokens WHERE token = ?", (token,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    if row['expires_at'] and datetime.datetime.now().isoformat() > row['expires_at']:
        return False
    return True


def create_api_token(name, created_by):
    import secrets as _s
    token = _s.token_urlsafe(32)
    conn = _admin_conn()
    conn.execute(
        "INSERT INTO api_tokens (token, name, created_by, created_at) VALUES (?, ?, ?, ?)",
        (token, name, created_by, datetime.datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return token


def list_api_tokens():
    conn = _admin_conn()
    rows = conn.execute(
        "SELECT id, name, token, created_by, created_at, expires_at FROM api_tokens"
    ).fetchall()
    conn.close()
    return rows


def delete_api_token(token_id):
    conn = _admin_conn()
    conn.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
    conn.commit()
    conn.close()


# ============================================================
# MariaDB — Kamailio data
# ============================================================

def get_mariadb():
    """Connect to MariaDB with retry + exponential backoff."""
    last_error = None
    for attempt in range(Config.DB_RETRY_ATTEMPTS):
        try:
            conn = pymysql.connect(
                host=Config.MARIADB_HOST,
                port=Config.MARIADB_PORT,
                user=Config.MARIADB_USER,
                password=Config.MARIADB_PASS,
                database=Config.MARIADB_DB,
                charset='utf8mb4',
                connect_timeout=Config.DB_CONNECTION_TIMEOUT,
                cursorclass=pymysql.cursors.DictCursor
            )
            if conn.open:
                return conn
            conn.close()
            raise Exception("Connection not established")
        except Exception as e:
            last_error = e
            if attempt < Config.DB_RETRY_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
    print(f"[SIPMAN] DB connection failed: {last_error}", file=sys.stderr, flush=True)
    return None


def check_mariadb():
    """Return (bool, message)."""
    try:
        conn = get_mariadb()
        if conn:
            conn.cursor().execute("SELECT 1")
            conn.close()
            return True, "Connected"
        return False, "Cannot connect"
    except Exception as e:
        return False, str(e)


def db_query(query, params=None):
    """Read query with retry — returns list of dicts."""
    last_error = None
    for attempt in range(Config.DB_RETRY_ATTEMPTS):
        conn = None
        try:
            conn = get_mariadb()
            if conn is None:
                time.sleep(2 ** attempt)
                continue
            cur = conn.cursor()
            cur.execute(query, params or ())
            rows = cur.fetchall()
            conn.close()
            return rows
        except Exception as e:
            last_error = e
            if conn:
                try: conn.close()
                except: pass
            if attempt < Config.DB_RETRY_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
    print(f"[SIPMAN] DB query failed: {last_error}", file=sys.stderr, flush=True)
    return []


def db_execute(query, params=None):
    """Write query with retry — returns lastrowid or None."""
    last_error = None
    for attempt in range(Config.DB_RETRY_ATTEMPTS):
        conn = None
        try:
            conn = get_mariadb()
            if conn is None:
                time.sleep(2 ** attempt)
                continue
            cur = conn.cursor()
            cur.execute(query, params or ())
            conn.commit()
            lastrowid = cur.lastrowid
            conn.close()
            return lastrowid
        except Exception as e:
            last_error = e
            if conn:
                try: conn.close()
                except: pass
            if attempt < Config.DB_RETRY_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
    print(f"[SIPMAN] DB execute failed: {last_error}", file=sys.stderr, flush=True)
    return None
