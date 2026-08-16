# SIP Manager - Pure Kamailio Web Management UI

A lightweight, free-software web management interface for Kamailio SIP proxy,
replacing dSIPRouter with a clean, minimal, well-documented setup.

## Overview

This project provides:

1. **Pure Kamailio SIP proxy** - Clean kamailio.cfg without dSIPRouter bloat
2. **RTPEngine** - Media relay for NAT traversal (unchanged from existing)
3. **Custom Flask Web UI** - User/domain/gateway management + monitoring
4. **nginx reverse proxy** - TLS termination on port 5000

## Quick Start

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
python app.py
# Visit http://127.0.0.1:8080
```

### Production Deployment

On the target server (sip.mrnet.work):

```bash
# 1. Upload configs to /tmp/sipman_configs/
# 2. Upload app to /tmp/sipman_app/
# 3. Run deployment script
sudo bash deploy.sh
```

## Architecture

```
                    ┌──────────────────────────────┐
                    │       sip.mrnet.work         │
                    └──────────────────────────────┘
                         SIP 5060/5061
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌─────────────┐    ┌──────────────┐    ┌──────────────────┐
│   nginx     │    │  Kamailio    │    │   RTPEngine      │
│  (port 5000)│    │  (port 5060) │    │  (port 7722 ctl) │
│  TLS proxy  │    │  SIP proxy   │    │  media relay     │
└─────┬───────┘    └──────┬───────┘    └────────┬─────────┘
      │                   │                    │
      ▼           kamcmd   │              rtpengine
┌─────────────┐   unix    │                    │
│ Flask/gunicorn │ ◄──────┘                    │
│  Web UI     │                            ng ctrl
└─────────────┘                            udp:127.0.0.1
      │                                          │
      │ MariaDB                                  ▼
      │  3306                                  Media
      └────────────────────────────────────── UDP
```

## Features

### Web UI Features
- **Login/Auth**: Session-based with bcrypt password hashing
- **SIP Users**: List, add, edit, delete subscribers (auto-computes HA1)
- **Domains**: List, add, delete SIP domains
- **Gateways**: View and manage dispatcher/carrier gateways
- **Monitoring**: Active registrations, active calls, recent CDRs
- **System Status**: Service health checks, Kamailio stats, DB test
- **API**: JSON-RPC proxy to kamcmd, user/domains/gateways REST API

### Kamailio Features
- SIP registration with digest authentication
- Location tracking (usrloc)
- NAT traversal with force_rport and SDP rewriting
- RTPEngine integration for media relaying
- Dispatcher-based carrier routing with health checks
- Accounting (acc) to MariaDB
- TLS support on port 5061
- Rate limiting (pike) and flood protection
- Multiple listen interfaces (internal + external)

## Default Credentials

- **Web UI**: admin / admin
- **SIP Users**: All use password `Morton@1645`
  - Extensions: 100, 102, 430, 764, 765, 784, 783

## Configuration

### Environment Variables

```
FLASK_SECRET_KEY=...          # Session secret (change in production!)
MARIADB_HOST=localhost        # Kamailio DB host
MARIADB_PORT=3306             # Kamailio DB port
MARIADB_USER=sipman           # Kamailio DB user (dedicated app user)
MARIADB_PASS=<see service>    # Kamailio DB password (stored in systemd unit)
MARIADB_DB=kamailio           # Kamailio DB name
SIPMAN_DB_PATH=/run/sipman/sipman.db  # SQLite path for admin users
KAMCMD_SOCKET=/var/run/kamailio/kamailio_ctl
SIPMAN_ADMIN_USER=admin       # Initial admin username
SIPMAN_ADMIN_PASS=<see note>  # Initial admin password (change immediately!)
```

### Default Credentials

- **Web UI**: `admin` / `ChangeMeNow!2026#sipman`
  - **IMPORTANT**: Change this immediately after first login via `/profile`
- **SIP Users**: All use password `Morton@1645`
  - Extensions: 100, 102, 430, 764, 765, 784, 783

### API Usage

### Login (get session)
```bash
curl -sk -X POST https://sip.mrnet.work:5000/login -d "username=admin&password=ChangeMeNow!2026#sipman" -c cookies.txt
```

### API (JWT bearer token)
```bash
# First login to get token
TOKEN=$(curl -sk -X POST https://sip.mrnet.work:5000/api/v1/login \
  -d "username=admin&password=ChangeMeNow!2026#sipman" | jq -r .token)

# Use token
curl -sk https://sip.mrnet.work:5000/api/v1/statistics \
  -H "Authorization: Bearer $TOKEN"
```

### Kamailio Commands (via web UI API)
```bash
# List active dialogs
curl -sk https://sip.mrnet.work:5000/api/v1/kamcmd/dlg.list -H "Authorization: Bearer $TOKEN"

# Core stats
curl -sk https://sip.mrnet.work:5000/api/v1/kamcmd/core.stats -H "Authorization: Bearer $TOKEN"
```

## File Structure

```
/opt/sipman/
├── app.py                    # Flask application
├── requirements.txt          # Python dependencies
├── sipman.db                 # SQLite (admin users, API tokens)
├── templates/
│   ├── login.html            # Login page
│   ├── dashboard.html        # Main dashboard
│   ├── users.html            # SIP user list
│   ├── user_form.html        # Add/edit user form
│   ├── domains.html          # Domain list
│   ├── domain_form.html      # Add/edit domain form
│   ├── gateways.html         # Gateway list
│   ├── gateway_form.html     # Add gateway form
│   ├── monitoring.html       # Call monitoring
│   ├── system.html           # System status
│   ├── profile.html          # Admin profile
│   ├── 404.html              # Error page
│   └── 500.html              # Error page
├── static/                   # Static assets
└── configs/
    ├── kamailio.cfg          # Pure Kamailio config
    ├── nginx-sipman.conf     # nginx reverse proxy config
    └── sipman-web.service    # systemd service file
```

## Troubleshooting

### Web UI won't start
```bash
journalctl -u sipman-web -n 50 --no-pager
```

### Kamailio won't reload
```bash
# Check config syntax
kamcmd -f /var/run/kamailio/kamailio_ctl core.version

# Check logs
tail -f /var/log/kamailio/kamailio.log
```

### Database connection issues
```bash
# Test MariaDB connection
mysql -u root -e "SELECT 1"

# Check kamailio user
mysql -u kamailio -pkamailiorw -e "SELECT count(*) FROM subscriber" kamailio
```

### SIP registration issues
```bash
# Check active registrations
kamcmd -f /var/run/kamailio/kamailio_ctl ul show

# Check Kamailio config
kamcmd -f /var/run/kamailio/kamailio_ctl core.version
```

## License

GPL v3 - Pure free software. No proprietary components.
