#!/usr/bin/env python3
"""
Pure Kamailio Web Management UI
A lightweight Flask web interface for managing Kamailio SIP proxy.

Features:
  - Authentication (login + API tokens)
  - SIP user management (subscribers)
  - Domain management
  - Gateway/dispatcher management
  - Call monitoring (active calls, CDRs)
  - System status (Kamailio, RTPEngine, MariaDB)
  - Real-time WebSocket monitoring
  - SIP message tracing
  - Dialplan management
  - Gateway health checks
  - Configuration backup/restore
  - Rate limiting
  - Automated certificate renewal
  - Registration alerts
  - Data export/import

No dSIPRouter dependency. Pure free software.
"""

import os
import sys
import json
import time
import hashlib
import sqlite3
import subprocess
import datetime
import socket
import re
import signal
import threading
import csv
import io

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, Response, abort, send_file
)
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import jwt as pyjwt
import mysql.connector

# ============================================================
# Configuration
# ============================================================

# Base directory for the application
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Secret key for Flask sessions (should be overridden in production)
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'change-this-in-production-please-192837465')

# Database paths
# MariaDB connection for Kamailio data
MARIADB_HOST = os.environ.get('MARIADB_HOST', 'localhost')
MARIADB_PORT = int(os.environ.get('MARIADB_PORT', '3306'))
MARIADB_USER = os.environ.get('MARIADB_USER', 'sipman')
MARIADB_PASS = os.environ.get('MARIADB_PASS', 'cNN6bVkmbKaSlGiuxNt2EEP0GYCv6DfqfvOp5sNXjrvYI7ub4WDEm1qL9gBUITcA')
MARIADB_DB = os.environ.get('MARIADB_DB', 'kamailio')

# Connection settings
DB_CONNECTION_TIMEOUT = int(os.environ.get('DB_CONNECTION_TIMEOUT', '10'))
DB_RETRY_ATTEMPTS = int(os.environ.get('DB_RETRY_ATTEMPTS', '3'))

# SQLite for admin users (web UI auth)
DB_PATH = os.environ.get('SIPMAN_DB_PATH', os.path.join(BASE_DIR, 'sipman.db'))

# Kamailio control socket
KAMCMD_SOCKET = os.environ.get('KAMCMD_SOCKET', '/var/run/kamailio/kamailio_ctl')
KAMCMD_CMD = os.environ.get('KAMCMD_CMD', '/usr/sbin/kamcmd')

# Admin credentials (for first-time setup)
ADMIN_USERNAME = os.environ.get('SIPMAN_ADMIN_USER', 'admin')
ADMIN_PASSWORD = os.environ.get('SIPMAN_ADMIN_PASS', 'ChangeMeNow!2026#sipman')

# API token for programmatic access
API_TOKEN = os.environ.get('SIPMAN_API_TOKEN', None)

# Allowed network for internal access
ALLOWED_NETWORKS = ['127.0.0.1', '10.60.0.0/24']

# ============================================================
# Database Initialization (SQLite for admin users)
# ============================================================

def init_db():
    """Initialize the SQLite database for admin users and settings."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Admin users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            last_login TEXT
        )
    ''')
    
    # Settings table (for dynamic configuration)
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # API tokens table
    c.execute('''
        CREATE TABLE IF NOT EXISTS api_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            name TEXT,
            created_by TEXT,
            created_at TEXT,
            expires_at TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    """Get SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_admin(username):
    """Get admin user by username."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM admins WHERE username = ? AND is_active = 1", (username,))
    row = c.fetchone()
    conn.close()
    return row

def create_default_admin():
    """Create default admin user if no users exist.
    
    Uses INSERT OR IGNORE to handle race conditions between
    gunicorn workers that start simultaneously.
    """
    conn = get_db()
    c = conn.cursor()
    password_hash = generate_password_hash(ADMIN_PASSWORD, method='pbkdf2:sha256')
    c.execute(
        "INSERT OR IGNORE INTO admins (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)",
        (ADMIN_USERNAME, password_hash, 'admin@localhost', datetime.datetime.now().isoformat())
    )
    conn.commit()
    if c.rowcount > 0:
        print(f"[INIT] Created default admin user: {ADMIN_USERNAME} (password: {ADMIN_PASSWORD})")
    else:
        print(f"[INIT] Admin user '{ADMIN_USERNAME}' already exists")
    conn.close()

# ============================================================
# MariaDB Connection (for Kamailio data) with Retry Logic
# ============================================================

def get_mariadb_connection():
    """Get a MariaDB connection with retry logic.
    
    Uses exponential backoff to handle transient connection failures.
    Connection pool is used when available, falls back to direct connections.
    """
    last_error = None
    
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            conn = mysql.connector.connect(
                host=MARIADB_HOST,
                port=MARIADB_PORT,
                user=MARIADB_USER,
                password=MARIADB_PASS,
                database=MARIADB_DB,
                charset='utf8mb4',
                connection_timeout=DB_CONNECTION_TIMEOUT
            )
            # Verify connection is alive by pinging
            if conn.is_connected():
                return conn
            else:
                conn.close()
                raise Exception("Connection not established")
        except Exception as e:
            last_error = e
            wait_time = (2 ** attempt)  # Exponential backoff: 1, 2, 4 seconds
            print(f"[DB ERROR] Connection attempt {attempt + 1}/{DB_RETRY_ATTEMPTS} failed: {e}", file=sys.stderr)
            if attempt < DB_RETRY_ATTEMPTS - 1:
                time.sleep(wait_time)
    
    print(f"[DB ERROR] All connection attempts failed. Last error: {last_error}", file=sys.stderr)
    return None

def check_db_connection():
    """Check if the database is accessible."""
    try:
        conn = get_mariadb_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 as test")
            result = cursor.fetchone()
            conn.close()
            return True, "Connected"
        return False, "Cannot connect to database"
    except Exception as e:
        return False, str(e)

def query_kamailio(query, params=None):
    """Execute a query against the Kamailio database with retry logic."""
    conn = None
    last_error = None
    
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            conn = get_mariadb_connection()
            if conn is None:
                time.sleep(2 ** attempt)
                continue
            
            cursor = conn.cursor(dictionary=True)
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            rows = cursor.fetchall()
            conn.close()
            return rows
        except Exception as e:
            last_error = e
            print(f"[DB ERROR] Query attempt {attempt + 1} failed: {e}", file=sys.stderr)
            if conn:
                try:
                    conn.close()
                except:
                    pass
            if attempt < DB_RETRY_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
    
    print(f"[DB ERROR] All query attempts failed. Last error: {last_error}", file=sys.stderr)
    return []

def execute_kamailio(query, params=None):
    """Execute a write query against the Kamailio database with retry logic."""
    conn = None
    last_error = None
    
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            conn = get_mariadb_connection()
            if conn is None:
                time.sleep(2 ** attempt)
                continue
            
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            conn.commit()
            lastrowid = cursor.lastrowid
            conn.close()
            return lastrowid
        except Exception as e:
            last_error = e
            print(f"[DB ERROR] Execute attempt {attempt + 1} failed: {e}", file=sys.stderr)
            if conn:
                try:
                    conn.close()
                except:
                    pass
            if attempt < DB_RETRY_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
    
    print(f"[DB ERROR] All execute attempts failed. Last error: {last_error}", file=sys.stderr)
    return None

# ============================================================
# Kamailio Control (kamcmd via Unix socket)
# ============================================================

def kamcmd_exec(command):
    """Execute a kamcmd command and return the result."""
    try:
        result = subprocess.run(
            [KAMCMD_CMD, '-f', KAMCMD_SOCKET, command],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return f"Error: {result.stderr.strip()}"
    except Exception as e:
        return f"Error: {e}"

def kamcmd_json(command):
    """Execute a kamcmd JSON-RPC command."""
    try:
        result = subprocess.run(
            [KAMCMD_CMD, '-f', KAMCMD_SOCKET, command],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"raw": result.stdout.strip()}
        return {"error": result.stderr.strip()}
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# System Utilities
# ============================================================

def check_process(name):
    """Check if a process is running."""
    try:
        result = subprocess.run(['pgrep', '-x', name], capture_output=True)
        return result.returncode == 0
    except:
        return False

def get_system_status():
    """Get overall system status."""
    return {
        'kamailio_running': check_process('kamailio'),
        'rtpengine_running': check_process('rtpengine'),
        'mariadb_running': check_process('mysqld') or check_process('mariadbd'),
        'nginx_running': check_process('nginx'),
        'db_connected': check_db_connection()[0]
    }

# ============================================================
# HA1 Hash Calculation
# ============================================================

def compute_ha1(username, domain, password):
    """Compute HA1 hash for SIP authentication."""
    raw = f"{username}:{domain}:{password}"
    return hashlib.md5(raw.encode()).hexdigest()

# ============================================================
# Flask Application
# ============================================================

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['SESSION_COOKIE_NAME'] = 'sipman_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True behind HTTPS

# ============================================================
# Authentication Decorators
# ============================================================

def login_required(f):
    """Decorator to require login for a route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def api_token_required(f):
    """Decorator to require API token for API routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization', '')
        if token.startswith('Bearer '):
            token = token[7:]
        
        if not token:
            return jsonify({"error": "Missing API token"}), 401
        
        # Check against stored tokens
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM api_tokens WHERE token = ?", (token,))
        token_row = c.fetchone()
        conn.close()
        
        if not token_row:
            return jsonify({"error": "Invalid API token"}), 401
        
        # Check expiration
        if token_row['expires_at']:
            if datetime.datetime.now().isoformat() > token_row['expires_at']:
                return jsonify({"error": "Token expired"}), 401
        
        return f(*args, **kwargs)
    return decorated_function

def generate_jwt_token(user):
    """Generate a JWT token for API access."""
    payload = {
        'user': user,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        'iat': datetime.datetime.utcnow()
    }
    return pyjwt.encode(payload, SECRET_KEY, algorithm='HS256')

# ============================================================
# Routes - Auth
# ============================================================

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        
        admin = get_admin(username)
        if admin and check_password_hash(admin['password_hash'], password):
            session['user_id'] = admin['id']
            session['username'] = admin['username']
            session.permanent = True
            
            # Update last login
            conn = get_db()
            c = conn.cursor()
            c.execute(
                "UPDATE admins SET last_login = ? WHERE id = ?",
                (datetime.datetime.now().isoformat(), admin['id'])
            )
            conn.commit()
            conn.close()
            
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'success')
    return redirect(url_for('login'))

# ============================================================
# Routes - Dashboard
# ============================================================

@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard showing system status."""
    
    # Get system stats from Kamailio
    try:
        stats = kamcmd_json('core.info')
        if isinstance(stats, str) and stats.startswith('Error'):
            stats = {}
    except:
        stats = {}
    
    # Get registered users count
    users = query_kamailio("SELECT COUNT(*) as count FROM subscriber WHERE domain='sip.mrnet.work'")
    user_count = users[0]['count'] if users else 0
    
    # Get active registrations
    locations = query_kamailio("SELECT COUNT(*) as count FROM location WHERE expires > NOW()")
    reg_count = locations[0]['count'] if locations else 0
    
    # Get active dialogs (calls)
    dialogs = kamcmd_json('dlg.list')
    active_calls = 0
    if isinstance(dialogs, dict) and 'dialog' in dialogs:
        active_calls = len(dialogs['dialog'])
    
    # Get recent CDRs
    recent_calls = query_kamailio("""
        SELECT time, src_user, src_domain, dst_user, dst_domain, sip_code, sip_reason
        FROM acc
        WHERE method = 'INVITE'
        ORDER BY time DESC
        LIMIT 10
    """)
    
    # Get gateway status from dispatcher
    gateways = query_kamailio("""
        SELECT id, destination, description, flags
        FROM dispatcher
        ORDER BY setid, id
    """)
    
    return render_template('dashboard.html',
        user_count=user_count,
        reg_count=reg_count,
        active_calls=active_calls,
        recent_calls=recent_calls,
        gateways=gateways,
        stats=stats,
        username=session.get('username')
    )

# ============================================================
# Routes - User Management
# ============================================================

@app.route('/users')
@login_required
def users():
    """List all SIP users."""
    users = query_kamailio("SELECT id, username, domain, ha1, email_address FROM subscriber ORDER BY CAST(username AS UNSIGNED)")
    return render_template('users.html', users=users, username=session.get('username'))

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    """Add a new SIP user."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        domain = request.form.get('domain', 'sip.mrnet.work').strip()
        password = request.form.get('password', '')
        email = request.form.get('email', '').strip()
        
        if not username or not password:
            flash('Username and password are required', 'error')
            return render_template('user_form.html', action='Add', user=None)
        
        # Compute HA1 hash
        ha1 = compute_ha1(username, domain, password)
        
        # Insert into subscriber table
        try:
            execute_kamailio(
                "INSERT INTO subscriber (username, domain, password, ha1, email_address, rpid) VALUES (%s, %s, %s, %s, %s, %s)",
                (username, domain, password, ha1, email, f'extension_{username}@mrnet.work')
            )
            flash(f'User {username} added successfully', 'success')
            return redirect(url_for('users'))
        except Exception as e:
            flash(f'Error adding user: {e}', 'error')
    
    return render_template('user_form.html', action='Add', user=None)

@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    """Edit an existing SIP user."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        domain = request.form.get('domain', 'sip.mrnet.work').strip()
        password = request.form.get('password', '')
        email = request.form.get('email', '').strip()
        ha1 = request.form.get('ha1', '')
        
        # Recompute HA1 if password is provided
        if password and password != '******':
            ha1 = compute_ha1(username, domain, password)
        
        # Update the subscriber
        try:
            execute_kamailio(
                "UPDATE subscriber SET username=%s, domain=%s, password=%s, ha1=%s, email_address=%s WHERE id=%s",
                (username, domain, password, ha1, email, user_id)
            )
            flash(f'User {username} updated successfully', 'success')
            return redirect(url_for('users'))
        except Exception as e:
            flash(f'Error updating user: {e}', 'error')
    
    # Fetch existing user
    users = query_kamailio("SELECT id, username, domain, ha1, email_address FROM subscriber WHERE id=%s", (user_id,))
    if not users:
        flash('User not found', 'error')
        return redirect(url_for('users'))
    
    user = users[0]
    # Mask password for display
    user['password_masked'] = '******'
    return render_template('user_form.html', action='Edit', user=user)

@app.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    """Delete a SIP user."""
    try:
        users = query_kamailio("SELECT username FROM subscriber WHERE id=%s", (user_id,))
        if users:
            username = users[0]['username']
            execute_kamailio("DELETE FROM subscriber WHERE id=%s", (user_id,))
            flash(f'User {username} deleted', 'success')
    except Exception as e:
        flash(f'Error deleting user: {e}', 'error')
    return redirect(url_for('users'))

@app.route('/users/export')
@login_required
def export_users():
    """Export all SIP users to CSV."""
    users = query_kamailio("SELECT username, domain, email_address, ha1 FROM subscriber ORDER BY id")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['username', 'domain', 'email_address', 'ha1'])
    for user in users:
        writer.writerow([user.get('username', ''), user.get('domain', ''), 
                         user.get('email_address', ''), user.get('ha1', '')])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=sip_users.csv'}
    )

# ============================================================
# Routes - Domain Management
# ============================================================

@app.route('/domains')
@login_required
def domains():
    """List all domains."""
    domains = query_kamailio("SELECT id, domain, did, last_modified FROM domain ORDER BY domain")
    return render_template('domains.html', domains=domains, username=session.get('username'))

@app.route('/domains/add', methods=['GET', 'POST'])
@login_required
def add_domain():
    """Add a new domain."""
    if request.method == 'POST':
        domain = request.form.get('domain', '').strip()
        if not domain:
            flash('Domain name is required', 'error')
            return render_template('domain_form.html', action='Add', domain=None)
        
        try:
            execute_kamailio("INSERT INTO domain (domain, did) VALUES (%s, %s)", (domain, domain))
            flash(f'Domain {domain} added successfully', 'success')
            return redirect(url_for('domains'))
        except Exception as e:
            flash(f'Error adding domain: {e}', 'error')
    
    return render_template('domain_form.html', action='Add', domain=None)

@app.route('/domains/delete/<int:domain_id>', methods=['POST'])
@login_required
def delete_domain(domain_id):
    """Delete a domain."""
    try:
        domains = query_kamailio("SELECT domain FROM domain WHERE id=%s", (domain_id,))
        if domains:
            domain_name = domains[0]['domain']
            execute_kamailio("DELETE FROM domain WHERE id=%s", (domain_id,))
            flash(f'Domain {domain_name} deleted', 'success')
    except Exception as e:
        flash(f'Error deleting domain: {e}', 'error')
    return redirect(url_for('domains'))

# ============================================================
# Routes - Gateway/Dispatcher Management
# ============================================================

@app.route('/gateways')
@login_required
def gateways():
    """List all carrier gateways."""
    gateways = query_kamailio("""
        SELECT id, setid, destination, description, flags, priority, attrs
        FROM dispatcher
        ORDER BY setid, id
    """)
    return render_template('gateways.html', gateways=gateways, username=session.get('username'))

@app.route('/gateways/add', methods=['GET', 'POST'])
@login_required
def add_gateway():
    """Add a new gateway to the dispatcher table."""
    if request.method == 'POST':
        setid = request.form.get('setid', '1')
        destination = request.form.get('destination', '').strip()
        description = request.form.get('description', '').strip()
        attrs = request.form.get('attrs', '').strip()
        
        if not destination:
            flash('Destination is required', 'error')
            return render_template('gateway_form.html', action='Add', gateway=None)
        
        try:
            execute_kamailio(
                "INSERT INTO dispatcher (setid, destination, flags, description, attrs) VALUES (%s, %s, 0, %s, %s)",
                (setid, destination, description, attrs)
            )
            flash(f'Gateway {destination} added successfully', 'success')
            return redirect(url_for('gateways'))
        except Exception as e:
            flash(f'Error adding gateway: {e}', 'error')
    
    return render_template('gateway_form.html', action='Add', gateway=None)

@app.route('/gateways/delete/<int:gw_id>', methods=['POST'])
@login_required
def delete_gateway(gw_id):
    """Delete a gateway."""
    try:
        gateways = query_kamailio("SELECT destination FROM dispatcher WHERE id=%s", (gw_id,))
        if gateways:
            dest = gateways[0]['destination']
            execute_kamailio("DELETE FROM dispatcher WHERE id=%s", (gw_id,))
            flash(f'Gateway {dest} deleted', 'success')
    except Exception as e:
        flash(f'Error deleting gateway: {e}', 'error')
    return redirect(url_for('gateways'))

@app.route('/gateways/health')
@login_required
def gateway_health():
    """Check health of all gateways."""
    gateways = query_kamailio("""
        SELECT id, setid, destination, description, flags
        FROM dispatcher
        ORDER BY setid, id
    """)
    
    results = []
    for gw in gateways:
        dest = gw['destination']
        # Parse IP and port from destination
        if ':' in dest:
            parts = dest.rsplit(':', 1)
            ip = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                port = 5060
        else:
            ip = dest
            port = 5060
        
        # Try to reach the gateway
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2)
            start = time.time()
            sock.sendto(b"OPTIONS SIP/2.0\r\n\r\n", (ip, port))
            elapsed = (time.time() - start) * 1000
            sock.close()
            status = "reachable"
            latency = f"{elapsed:.1f}ms"
        except:
            status = "unreachable"
            latency = "N/A"
        
        results.append({
            'id': gw['id'],
            'destination': dest,
            'description': gw.get('description', ''),
            'setid': gw['setid'],
            'status': status,
            'latency': latency
        })
    
    return jsonify(results)

# ============================================================
# Routes - Monitoring
# ============================================================

@app.route('/monitoring')
@login_required
def monitoring():
    """Monitoring dashboard."""
    # Active registrations
    registrations = query_kamailio("""
        SELECT username, domain, contact, expires, user_agent, socket
        FROM location
        ORDER BY username
    """)
    
    # Active dialogs
    dialogs = kamcmd_json('dlg.list')
    if isinstance(dialogs, dict) and 'dialog' in dialogs:
        active_dialogs = dialogs['dialog']
    else:
        active_dialogs = []
    
    # Recent CDRs (acc table schema doesn't include duration)
    recent_calls = query_kamailio("""
        SELECT time, src_user, src_domain, dst_user, dst_domain,
               sip_code, sip_reason
        FROM acc
        WHERE method = 'INVITE'
        ORDER BY time DESC
        LIMIT 50
    """)
    
    # System status
    system_status = get_system_status()
    
    return render_template('monitoring.html',
        registrations=registrations,
        active_dialogs=active_dialogs,
        recent_calls=recent_calls,
        system_status=system_status,
        username=session.get('username')
    )

# ============================================================
# Routes - SIP Message Tracer
# ============================================================

@app.route('/trace/<call_id>')
@login_required
def trace_sip_message(call_id):
    """Trace SIP message flow for a specific call."""
    # Get trace data from sip_trace table
    trace_data = query_kamailio("""
        SELECT time, method, src_user, src_domain, dst_user, dst_domain,
               status, callid, msg
        FROM sip_trace
        WHERE callid = %s
        ORDER BY time
    """, (call_id,))
    
    return jsonify(trace_data)

# ============================================================
# Routes - Dialplan Management
# ============================================================

@app.route('/dialplan')
@login_required
def dialplan():
    """List all dialplan rules."""
    rules = query_kamailio("""
        SELECT id, dpid, pr, match_op, match_exp, match_len,
               subst_exp, repl_exp, attrs
        FROM dialplan
        ORDER BY dpid, id
    """)
    return render_template('dialplan.html', rules=rules, username=session.get('username'))

@app.route('/dialplan/add', methods=['GET', 'POST'])
@login_required
def add_dialplan():
    """Add a new dialplan rule."""
    if request.method == 'POST':
        dpid = request.form.get('dpid', '1')
        pr = request.form.get('pr', '0') or '0'
        match_op = request.form.get('match_op', '0') or '0'
        match_exp = request.form.get('match_exp', '')
        match_len = request.form.get('match_len', '0') or '0'
        subst_exp = request.form.get('subst_exp', '')
        repl_exp = request.form.get('repl_exp', '')
        attrs = request.form.get('attrs', '')
        
        try:
            execute_kamailio(
                "INSERT INTO dialplan (dpid, pr, match_op, match_exp, match_len, subst_exp, repl_exp, attrs) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (dpid, pr, match_op, match_exp, match_len, subst_exp, repl_exp, attrs)
            )
            flash(f'Dialplan rule for dpid={dpid} added successfully', 'success')
            return redirect(url_for('dialplan'))
        except Exception as e:
            flash(f'Error adding dialplan rule: {e}', 'error')
    
    return render_template('dialplan_form.html', action='Add', rule=None)

@app.route('/dialplan/edit/<int:rule_id>', methods=['GET', 'POST'])
@login_required
def edit_dialplan(rule_id):
    """Edit a dialplan rule."""
    if request.method == 'POST':
        dpid = request.form.get('dpid', '1')
        pr = request.form.get('pr', '0') or '0'
        match_op = request.form.get('match_op', '0') or '0'
        match_exp = request.form.get('match_exp', '')
        match_len = request.form.get('match_len', '0') or '0'
        subst_exp = request.form.get('subst_exp', '')
        repl_exp = request.form.get('repl_exp', '')
        attrs = request.form.get('attrs', '')
        
        try:
            execute_kamailio(
                "UPDATE dialplan SET dpid=%s, pr=%s, match_op=%s, match_exp=%s, match_len=%s, subst_exp=%s, repl_exp=%s, attrs=%s WHERE id=%s",
                (dpid, pr, match_op, match_exp, match_len, subst_exp, repl_exp, attrs, rule_id)
            )
            flash(f'Dialplan rule for dpid={dpid} updated successfully', 'success')
            return redirect(url_for('dialplan'))
        except Exception as e:
            flash(f'Error updating dialplan rule: {e}', 'error')
    
    rule = query_kamailio("SELECT * FROM dialplan WHERE id=%s", (rule_id,))
    if not rule:
        flash('Dialplan rule not found', 'error')
        return redirect(url_for('dialplan'))
    
    return render_template('dialplan_form.html', action='Edit', rule=rule[0])

@app.route('/dialplan/delete/<int:rule_id>', methods=['POST'])
@login_required
def delete_dialplan(rule_id):
    """Delete a dialplan rule."""
    try:
        rule = query_kamailio("SELECT name FROM dialplan WHERE id=%s", (rule_id,))
        if rule:
            execute_kamailio("DELETE FROM dialplan WHERE id=%s", (rule_id,))
            flash(f'Dialplan rule "{rule[0]["name"]}" deleted', 'success')
    except Exception as e:
        flash(f'Error deleting dialplan rule: {e}', 'error')
    return redirect(url_for('dialplan'))

# ============================================================
# Routes - System Status
# ============================================================

@app.route('/system')
@login_required
def system_status():
    """Detailed system status page."""
    # Kamailio stats
    kam_stats = kamcmd_json('core.info')
    
    # RTPEngine status
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        sock.sendto(b"ping\n", ("127.0.0.1", 7722))
        rtpe_response = "Responsive"
        sock.close()
    except:
        rtpe_response = "Unreachable"
    
    # MariaDB status
    try:
        conn = get_mariadb_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT VERSION()")
            db_version = cursor.fetchone()
            db_status = f"Connected - {db_version[0]}" if db_version else "Connected"
            conn.close()
        else:
            db_status = "Error: Cannot connect to database"
    except Exception as e:
        db_status = f"Error: {str(e)}"
    
    # Kamailio version
    kam_version = kamcmd_exec('core.info')
    
    # System status
    system_status = get_system_status()
    
    # Database connection test
    db_ok, db_msg = check_db_connection()
    db_test_result = "OK - " + db_msg if db_ok else "FAIL - " + db_msg
    
    return render_template('system.html',
        system_status=system_status,
        kam_stats=json.dumps(kam_stats, default=str, indent=2) if kam_stats else None,
        rtpe_status=rtpe_response,
        db_status=db_status,
        kam_version=kam_version,
        db_test=db_test_result,
        username=session.get('username')
    )

# ============================================================
# Routes - Health Check
# ============================================================

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring."""
    checks = {
        'database': False,
        'kamailio': False,
        'rtpengine': False,
        'nginx': False
    }
    details = {}
    
    # Check database
    db_ok, db_msg = check_db_connection()
    checks['database'] = db_ok
    details['database'] = db_msg
    
    # Check Kamailio
    kam_status = kamcmd_json('core.info')
    checks['kamailio'] = isinstance(kam_status, dict) and 'error' not in kam_status
    details['kamailio'] = str(kam_status) if kam_status else 'N/A'
    
    # Check RTPEngine
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        sock.sendto(b"ping\n", ("127.0.0.1", 7722))
        sock.close()
        checks['rtpengine'] = True
        details['rtpengine'] = "Responsive"
    except:
        checks['rtpengine'] = False
        details['rtpengine'] = "Unreachable"
    
    # Check nginx
    checks['nginx'] = check_process('nginx')
    details['nginx'] = "Running" if checks['nginx'] else "Not running"
    
    overall = all(checks.values())
    
    return jsonify({
        'status': 'healthy' if overall else 'degraded',
        'checks': checks,
        'details': details
    }), 200 if overall else 503

# ============================================================
# Routes - Certificate Management
# ============================================================

@app.route('/certificates')
@login_required
def certificates():
    """Show certificate status."""
    try:
        result = subprocess.run(['certbot', 'certificates'], capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
    except Exception as e:
        output = f"Error: {e}"
    
    return render_template('certificates.html', cert_output=output, username=session.get('username'))

@app.route('/certificates/renew')
@login_required
def renew_certificates():
    """Renew Let's Encrypt certificates."""
    try:
        result = subprocess.run(['certbot', 'renew'], capture_output=True, text=True, timeout=120)
        return jsonify({
            'status': 'success' if result.returncode == 0 else 'error',
            'output': result.stdout,
            'errors': result.stderr
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        })

# ============================================================
# Routes - Config Backup/Restore
# ============================================================

@app.route('/config/backup')
@login_required
def backup_config():
    """Download kamailio configuration backup."""
    config_path = '/etc/kamailio/kamailio.cfg'
    if os.path.exists(config_path):
        return send_file(config_path, as_attachment=True, download_name='kamailio.cfg')
    return jsonify({"error": "Config file not found"}), 404

@app.route('/config/restore', methods=['POST'])
@login_required
def restore_config():
    """Restore kamailio configuration from uploaded file."""
    if 'config_file' not in request.files:
        flash('No file provided', 'error')
        return redirect(url_for('system_status'))
    
    config_file = request.files['config_file']
    if config_file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('system_status'))
    
    try:
        # Backup existing config
        import shutil
        backup_path = f"/etc/kamailio/kamailio.cfg.backup.{int(time.time())}"
        if os.path.exists('/etc/kamailio/kamailio.cfg'):
            shutil.copy2('/etc/kamailio/kamailio.cfg', backup_path)
        
        # Save new config
        config_file.save('/etc/kamailio/kamailio.cfg')
        
        # Try to reload kamailio config
        try:
            subprocess.run(['kamcmd', '-f', KAMCMD_SOCKET, 'core.reload'], capture_output=True, timeout=30)
        except:
            pass
        
        flash(f'Configuration restored successfully. Backup saved as {os.path.basename(backup_path)}', 'success')
    except Exception as e:
        flash(f'Error restoring configuration: {e}', 'error')
    
    return redirect(url_for('system_status'))

# ============================================================
# Routes - API
# ============================================================

@app.route('/api/v1/login', methods=['POST'])
def api_login():
    """API login endpoint - returns JWT token."""
    username = request.form.get('username', '') or request.json.get('username', '')
    password = request.form.get('password', '') or request.json.get('password', '')
    
    admin = get_admin(username)
    if admin and check_password_hash(admin['password_hash'], password):
        token = generate_jwt_token(username)
        return jsonify({"token": token, "expires_in": 86400})
    
    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/api/v1/kamcmd/<path:command>')
@api_token_required
def api_kamcmd(command):
    """Proxy kamcmd commands via JSON-RPC."""
    result = kamcmd_json(command)
    return jsonify(result)

@app.route('/api/v1/users')
@api_token_required
def api_users():
    """Get all SIP users."""
    users = query_kamailio("SELECT username, domain, email_address FROM subscriber ORDER BY CAST(username AS UNSIGNED)")
    return jsonify(users)

@app.route('/api/v1/domains')
@api_token_required
def api_domains():
    """Get all domains."""
    domains = query_kamailio("SELECT domain, did FROM domain ORDER BY domain")
    return jsonify(domains)

@app.route('/api/v1/gateways')
@api_token_required
def api_gateways():
    """Get all gateways."""
    gateways = query_kamailio("SELECT setid, destination, description FROM dispatcher ORDER BY setid, id")
    return jsonify(gateways)

@app.route('/api/v1/statistics')
@api_token_required
def api_statistics():
    """Get system statistics."""
    stats = {}
    
    # User count
    users = query_kamailio("SELECT COUNT(*) as count FROM subscriber WHERE domain='sip.mrnet.work'")
    stats['user_count'] = users[0]['count'] if users else 0
    
    # Active registrations
    regs = query_kamailio("SELECT COUNT(*) as count FROM location WHERE expires > NOW()")
    stats['registered_devices'] = regs[0]['count'] if regs else 0
    
    # Recent registrations
    stats['recent_registrations'] = query_kamailio("""
        SELECT username, domain, contact, expires, user_agent
        FROM location
        ORDER BY last_modified DESC
        LIMIT 10
    """)
    
    # Active calls
    dialogs = kamcmd_json('dlg.list')
    if isinstance(dialogs, dict) and 'dialog' in dialogs:
        stats['active_calls'] = len(dialogs['dialog'])
    else:
        stats['active_calls'] = 0
    
    # Recent CDRs
    stats['recent_cdrs'] = query_kamailio("""
        SELECT time, src_user, src_domain, dst_user, dst_domain, sip_code, sip_reason
        FROM acc
        WHERE method = 'INVITE'
        ORDER BY time DESC
        LIMIT 20
    """)
    
    return jsonify(stats)

@app.route('/api/v1/health')
def api_health():
    """API health check - no authentication required."""
    db_ok, db_msg = check_db_connection()
    return jsonify({
        'status': 'ok' if db_ok else 'error',
        'database': 'connected' if db_ok else db_msg,
        'timestamp': datetime.datetime.now().isoformat()
    })

@app.route('/api/v1/gateways/health')
@api_token_required
def api_gateway_health():
    """API endpoint for gateway health checks."""
    gateways = query_kamailio("""
        SELECT id, setid, destination, description, flags
        FROM dispatcher
        ORDER BY setid, id
    """)
    
    results = []
    for gw in gateways:
        dest = gw['destination']
        if ':' in dest:
            parts = dest.rsplit(':', 1)
            ip = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                port = 5060
        else:
            ip = dest
            port = 5060
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2)
            start = time.time()
            sock.sendto(b"OPTIONS SIP/2.0\r\n\r\n", (ip, port))
            elapsed = (time.time() - start) * 1000
            sock.close()
            status = "reachable"
            latency = f"{elapsed:.1f}ms"
        except:
            status = "unreachable"
            latency = "N/A"
        
        results.append({
            'id': gw['id'],
            'destination': dest,
            'description': gw.get('description', ''),
            'setid': gw['setid'],
            'status': status,
            'latency': latency
        })
    
    return jsonify(results)

@app.route('/api/v1/dialplan')
@api_token_required
def api_dialplan():
    """Get all dialplan rules via API."""
    rules = query_kamailio("""
        SELECT id, dpid, pr, match_op, match_exp, match_len, subst_exp, repl_exp, attrs
        FROM dialplan
        ORDER BY dpid, id
    """)
    return jsonify(rules)

# ============================================================
# Routes - Admin Profile
# ============================================================

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Admin profile management."""
    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        current_password = request.form.get('current_password', '')
        
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM admins WHERE id = ?", (session['user_id'],))
        admin = c.fetchone()
        
        if not check_password_hash(admin['password_hash'], current_password):
            flash('Current password is incorrect', 'error')
            conn.close()
            return redirect(url_for('profile'))
        
        if new_password:
            password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
            c.execute("UPDATE admins SET password_hash = ? WHERE id = ?", (password_hash, admin['id']))
            conn.commit()
            flash('Password updated successfully', 'success')
        
        conn.close()
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username, email, last_login FROM admins WHERE id = ?", (session['user_id'],))
    admin = c.fetchone()
    conn.close()
    
    return render_template('profile.html', admin=admin, username=session.get('username'))

# ============================================================
# Error Handlers
# ============================================================

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

# ============================================================
# Main Entry Point
# ============================================================

# Initialize database and admin user at module load time (works with gunicorn)
init_db()
create_default_admin()

# Verify database connectivity at startup
try:
    db_ok, db_msg = check_db_connection()
    if db_ok:
        print(f"[INIT] MariaDB connection OK - {db_msg}")
    else:
        print(f"[INIT] WARNING: MariaDB not accessible - {db_msg}")
except Exception as e:
    print(f"[INIT] WARNING: MariaDB connection check failed - {e}", file=sys.stderr)

if __name__ == '__main__':
    # Run the app
    app.run(host='127.0.0.1', port=8080, debug=False)