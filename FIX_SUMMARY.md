# SIP Manager Fix Summary

## Database Connection Issues — RESOLVED ✅

### Root Causes Identified

1. **Missing environment variables in systemd service file** — `MARIADB_USER` and `MARIADB_PASS` were not set in the deployed `sipman-web.service` on the server
2. **Wrong MariaDB credentials** — App defaulted to `root` with empty password, but MariaDB root uses socket authentication (auth_socket plugin)
3. **Missing retry logic** in DB connections on the server — transient failures crashed the app
4. **No health check endpoints** — had no way to diagnose connectivity issues
5. **Race condition in admin user creation** — 4 gunicorn workers tried to INSERT the same default admin simultaneously

### Fixes Applied

#### 1. MariaDB User Configuration
- Created dedicated `sipman` user in MariaDB with password matching the kamailio account
- Database password: `cNN6bVkmbKaSlGiuxNt2EEP0GYCv6DfqfvOp5sNXjrvYI7ub4WDEm1qL9gBUITcA`
- Granted `SELECT, INSERT, UPDATE, DELETE` on `kamailio.*` database
- This password matches the DBURL hardcoded in `/etc/kamailio/kamailio.cfg`

#### 2. Service File Fixes (`configs/sipman-web.service`)
- **Added missing environment variables**:
  ```
  Environment="MARIADB_USER=sipman"
  Environment="MARIADB_PASS=cNN6bVkmbKaSlGiuxNt2EEP0GYCv6DfqfvOp5sNXjrvYI7ub4WDEm1qL9gBUITcA"
  ```
- **Fixed WorkingDirectory**: Changed from `/home/user/sipman` to `/opt/sipman` (server deployment path)

#### 3. Application Code Fixes (`app.py`)
- **Added connection retry logic** with exponential backoff (3 attempts: 1s, 2s, 4s)
- **Added database health check endpoint** at `/health` and `/api/v1/health`
- **Added `INSERT OR IGNORE`** in `create_default_admin()` to handle race conditions between gunicorn workers
- **Verified DB connectivity at startup** with clear log messages
- **Fixed monitoring route SQL** to use columns that exist in the actual Kamailio `acc` table schema (removed `duration` column)
- **Fixed dialplan routes** to use standard Kamailio dialplan table columns (`pr`, `match_op`, `match_exp`, `match_len`, `subst_exp`, `repl_exp`, `attrs`) instead of dSIPRouter-specific columns (`name`, `match_user`, `match_caller_domain`, etc.)
- **Fixed template syntax error** in `monitoring.html` (extra `}` in `{{ dlg.state }`)
- **Added health check to nginx config** — proxies `/health` to Flask app for dynamic health check instead of static "OK"

### Database Credentials
- **sipman user**: `sipman` / `cNN6bVkmbKaSlGiuxNt2EEP0GYCv6DfqfvOp5sNXjrvYI7ub4WDEm1qL9gBUITcA` (matches kamailio.cfg DBURL)
- **kamailio user**: `kamailio` / same password (already existed, unchanged)
- **Root user**: socket authentication only (sudo mysql)

### Admin Credentials
- **Username**: `admin`
- **Password**: `ChangeMeNow!2026#sipman`
- **IMPORTANT**: Change this immediately after first login via `/profile`

### Deployment Status

| Component | Status | Notes |
|-----------|--------|-------|
| MariaDB | ✅ Active | sipman user created with correct password |
| sipman-web | ✅ Active (running) | gunicorn 23.0.0, 4 workers, all connected to DB |
| nginx | ✅ Active (reloaded) | Dynamic /health proxy to Flask |
| Kamailio | ✅ Active | Unchanged, DBURL password matches |
| RTPEngine | ✅ Active | Unchanged |
| All routes | ✅ HTTP 200 | dashboard, users, domains, gateways, monitoring, system, profile, certificates, dialplan, config/backup, users/export |
| No DB errors | ✅ Confirmed | Zero DB ERROR entries in logs |

### Verification Results
```
[INIT] MariaDB connection OK - Connected  (all 4 workers)
Health check: {"status": "healthy", "checks": {"database": true, "kamailio": true, "nginx": true, "rtpengine": true}}
API health: {"database": "connected", "status": "ok"}
Login: HTTP 302 (redirect to dashboard)
All routes: HTTP 200
No errors in logs
```

### Default Credentials
- **Web UI**: admin / `ChangeMeNow!2026#sipman`
- **SIP Users**: Password `Morton@1645` (extensions 100, 102, 430, 764, 765, 784, 783)

### Deployment Instructions
1. **Start MariaDB**: `sudo systemctl start mariadb`
2. **Install dependencies**: `sudo pip3 install flask pyjwt bcrypt mysql-connector-python gunicorn werkzeug`
3. **Deploy configs**: Copy `configs/sipman-web.service` to `/etc/systemd/system/`
4. **Deploy app**: Copy `app.py` and `templates/` to `/opt/sipman/`
5. **Create sipman DB user**: `CREATE USER sipman@localhost IDENTIFIED BY '<password>'; GRANT SELECT,INSERT,UPDATE,DELETE ON kamailio.* TO sipman@localhost;`
6. **Start the service**: `sudo systemctl daemon-reload && sudo systemctl start sipman-web`

### Access
- URL: `https://sip.mrnet.work:5000/`
- Health: `https://sip.mrnet.work:5000/health`
- API Health: `https://sip.mrnet.work:5000/api/v1/health`
