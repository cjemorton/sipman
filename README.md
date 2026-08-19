# SipMan Backend

A self-contained, Dockerized Kamailio SIP endpoint with a REST API for management. Designed for deployment in [Coolify](https://coolify.io) as a Docker container, with built-in multi-cluster peer sync for horizontal scaling.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Docker Container                   │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Kamailio │  │RTPEngine │  │  Flask API        │  │
│  │ (SIP)    │  │ (Media)  │  │  (gunicorn :5000) │  │
│  └────┬─────┘  └──────────┘  └────────┬──────────┘  │
│       │                                │              │
│  ┌────▼──────────────────────────────────▼────┐       │
│  │              MariaDB (Kamailio data)        │       │
│  └─────────────────────────────────────────────┘       │
│                                                      │
│  supervisord (process manager)                        │
└─────────────────────────────────────────────────────┘
         │                        │
    SIP 5060/5061              REST API :5000
    (internet-facing)          (proxy via Coolify/NPM)
```

The **Cloudflare Worker frontend** (`sipman-worker`) talks to the REST API on port 5000. SIP clients register directly to port 5060.

## What's Inside

| Component | Purpose |
|-----------|---------|
| **Kamailio** | SIP proxy — registration, routing, auth, NAT traversal |
| **RTPEngine** | Media relay — handles RTP traffic between endpoints |
| **MariaDB** | Stores subscribers, locations, domains, dispatcher, CDRs |
| **Flask API** | REST API for the Worker frontend to manage the endpoint |
| **supervisord** | Manages all processes, auto-restart on crash |

## REST API

All endpoints under `/api/v1/` require JWT authentication (except `/health` and `/api/v1/login`).

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/login` | Authenticate, get JWT token |
| GET | `/api/v1/cluster` | Cluster identity & status |
| GET | `/api/v1/clusters` | List all known clusters |
| POST | `/api/v1/clusters` | Register a cluster |
| POST | `/api/v1/cluster/sync` | Trigger full data push to peers |
| GET | `/api/v1/users` | List SIP users |
| POST | `/api/v1/users` | Create SIP user |
| GET | `/api/v1/users/:id` | Get single user |
| PUT | `/api/v1/users/:id` | Update user |
| DELETE | `/api/v1/users/:id` | Delete user |
| GET | `/api/v1/users/export` | Export users as CSV |
| GET | `/api/v1/domains` | List domains |
| POST | `/api/v1/domains` | Create domain |
| PUT | `/api/v1/domains/:id` | Update domain |
| DELETE | `/api/v1/domains/:id` | Delete domain |
| GET | `/api/v1/gateways` | List gateways |
| POST | `/api/v1/gateways` | Create gateway |
| PUT | `/api/v1/gateways/:id` | Update gateway |
| DELETE | `/api/v1/gateways/:id` | Delete gateway |
| GET | `/api/v1/gateways/health` | Ping all gateways |
| GET | `/api/v1/statistics` | Call stats, registrations, CDRs |
| GET | `/api/v1/monitoring` | Detailed monitoring data |
| GET | `/api/v1/profile` | Admin profile |
| PUT | `/api/v1/profile` | Change admin password |
| GET | `/health` | Health check (no auth) |

### Peer Sync (Internal, `X-Peer-Secret` auth)

| Method | Path | Description |
|--------|------|-------------|
| POST/PUT | `/sync/users` | Replicate subscriber |
| DELETE | `/sync/users` | Delete subscriber |
| POST/PUT | `/sync/domains` | Replicate domain |
| DELETE | `/sync/domains` | Delete domain |
| POST/PUT | `/sync/gateways` | Replicate gateway |
| DELETE | `/sync/gateways` | Delete gateway |
| POST | `/sync/full` | Full data sync |

## Deployment in Coolify

### 1. Deploy the Container

1. In Coolify, create a new resource → **Docker Compose** (or connect this Git repo)
2. The `docker-compose.yml` is auto-detected
3. Set the environment variables (see `.env.example`):
   - `SIP_DOMAIN` — your SIP domain (e.g. `sip.mrnet.work`)
   - `SIP_EXTERNAL_IP` — the server's public IP
   - `SIPMAN_ADMIN_PASS` — change the default admin password
   - `SIPMAN_JWT_SECRET` — must match the Worker's `JWT_SECRET`
   - `MARIADB_PASS` — set a strong database password
4. Deploy

### 2. Network

- **Port 5000** (API): Proxy through Coolify's built-in proxy or Nginx Proxy Manager. This is what the Cloudflare Worker connects to.
- **Ports 5060/5061** (SIP): Must be exposed directly to the internet (not proxied). SIP doesn't work well behind HTTP reverse proxies.
- **Ports 10000-20000/udp** (RTP): Media ports for RTPEngine. Must be open on the firewall.

### 3. Connect the Worker

In the Cloudflare Worker (`sipman-worker`), update `CLUSTER_BACKEND_URL` to point to this container's API:
```
CLUSTER_BACKEND_URL = https://sipman-api.yourdomain.com
```
Ensure `JWT_SECRET` in the Worker matches `SIPMAN_JWT_SECRET` in the container.

## Multi-Cluster Setup

To scale horizontally, deploy multiple instances. Each is independent but shares users, domains, and gateways via peer sync.

### How It Works

1. **API-level sync**: When you create a user on node-A, node-A replicates the change to node-B, node-C, etc. via `/sync/*` endpoints. All nodes have identical subscriber/domain/gateway tables.
2. **DMQ (SIP-level sync)**: Kamailio's DMQ module replicates live registration/location data between nodes, so a call to any node can reach a user registered on any other node.
3. **Independent operation**: If a peer goes down, the others continue working. When it comes back, trigger a full sync via `POST /api/v1/cluster/sync`.

### Configuring Peers

**Node A** (`CLUSTER_ID=node-a`):
```env
PEER_NODES=http://node-b-ip:5000,http://node-c-ip:5000
PEER_SYNC_SECRET=your-shared-secret-here
```

**Node B** (`CLUSTER_ID=node-b`):
```env
PEER_NODES=http://node-a-ip:5000,http://node-c-ip:5000
PEER_SYNC_SECRET=your-shared-secret-here
```

**Node C** (`CLUSTER_ID=node-c`):
```env
PEER_NODES=http://node-a-ip:5000,http://node-b-ip:5000
PEER_SYNC_SECRET=your-shared-secret-here
```

All nodes must share the same `PEER_SYNC_SECRET`.

### Registering Clusters in the Worker

In the Cloudflare Worker's `CLUSTER_CONFIG`, add each node:
```js
const CLUSTER_CONFIG = {
  "node-a": { name: "Node A", backend_url: "https://node-a-api.example.com", type: "primary" },
  "node-b": { name: "Node B", backend_url: "https://node-b-api.example.com", type: "secondary" },
  "node-c": { name: "Node C", backend_url: "https://node-c-api.example.com", type: "secondary" },
};
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLUSTER_ID` | `primary` | Unique ID for this node |
| `CLUSTER_NAME` | `SIP Manager Cluster` | Display name |
| `SIP_DOMAIN` | `sip.mrnet.work` | SIP domain |
| `SIP_EXTERNAL_IP` | `127.0.0.1` | Public IP for NAT traversal |
| `SIP_PORT` | `5060` | SIP signaling port |
| `SIPS_PORT` | `5061` | SIP TLS port |
| `MARIADB_DB` | `kamailio` | Database name |
| `MARIADB_USER` | `kamailio` | Database user |
| `MARIADB_PASS` | `kamailio` | Database password |
| `MARIADB_ROOT_PASS` | (empty) | MariaDB root password |
| `RTPENGINE_HOST` | `127.0.0.1` | RTPEngine control host |
| `RTPENGINE_PORT` | `7722` | RTPEngine control port |
| `RTPENGINE_INTERFACE` | `0.0.0.0` | RTPEngine bind interface |
| `SIPMAN_ADMIN_USER` | `admin` | Default admin username |
| `SIPMAN_ADMIN_PASS` | `ChangeMeNow!...` | Default admin password |
| `SIPMAN_JWT_SECRET` | (random) | JWT signing secret |
| `PEER_NODES` | (empty) | Comma-separated peer URLs |
| `PEER_SYNC_SECRET` | (empty) | Shared secret for peer auth |
| `PEER_SYNC_ENABLED` | `false` | Enable peer sync |
| `CLUSTER_BACKEND_URL` | (empty) | Public API URL |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |

## Project Structure

```
sipman/
├── app/                    # Flask application (modular)
│   ├── __init__.py         # App factory
│   ├── config.py           # Environment-based config
│   ├── auth.py             # JWT + token auth
│   ├── database.py         # SQLite + MariaDB layer
│   ├── kamailio.py         # kamcmd + process checks
│   ├── peers.py            # Peer sync logic
│   └── routes/             # REST API blueprints
│       ├── auth.py
│       ├── cluster.py
│       ├── domains.py
│       ├── gateways.py
│       ├── health.py
│       ├── peers.py
│       ├── profile.py
│       ├── statistics.py
│       └── users.py
├── docker/                 # Container configs
│   ├── entrypoint.sh       # Startup script
│   ├── supervisord.conf    # Process manager
│   ├── kamailio.cfg.tmpl   # Kamailio config template
│   ├── tls.cfg.tmpl        # TLS config template
│   └── dmq_helper.sh       # DMQ config generator
├── wsgi.py                 # Gunicorn entry point
├── Dockerfile              # Container image
├── docker-compose.yml      # Coolify deployment
├── requirements.txt        # Python deps
└── .env.example            # Environment template
```

## Building & Testing Locally

```bash
# Build
docker compose build

# Run
docker compose up -d

# Check health
curl http://localhost:5000/health

# Login (get JWT)
curl -X POST http://localhost:5000/api/v1/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"ChangeMeNow!2026#sipman"}'

# List users (replace TOKEN)
curl http://localhost:5000/api/v1/users \
  -H "Authorization: Bearer TOKEN"
```
