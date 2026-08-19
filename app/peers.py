"""
Peer-to-peer sync.
When a user/domain/gateway is created on one node, the same change is
replicated to every peer node via their internal /sync/* endpoints.

DMQ (Kamailio's built-in module) handles live registration/location sync
at the SIP layer. This module handles the *configuration* layer — keeping
subscriber, domain, and dispatcher tables identical across all nodes.

Flow:
  User creates SIP user on node-A  →  POST /api/v1/users
  Node-A writes to its own MariaDB  →  replicates to peers
  Node-B receives POST /sync/users  →  writes to its own MariaDB

Each node is independent: if a peer is down, the write succeeds locally
and the peer will catch up on next full-sync or manual re-sync.
"""

import hashlib
import json
import urllib.request
import urllib.error

from app.config import Config
from app.database import db_query, db_execute


def compute_ha1(username, domain, password):
    return hashlib.md5(f"{username}:{domain}:{password}".encode()).hexdigest()


def replicate_to_peers(endpoint, method, data):
    """
    Fire-and-forget POST/PUT/DELETE to all registered peers.

    endpoint: e.g. "/sync/users"  (internal API, not public)
    method:   "POST" | "PUT" | "DELETE"
    data:     dict payload
    """
    if not Config.PEER_SYNC_ENABLED or not Config.PEER_SYNC_SECRET:
        return

    peers = _get_peer_urls()
    for peer_url in peers:
        try:
            url = peer_url.rstrip('/') + endpoint
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode(),
                method=method,
                headers={
                    'Content-Type': 'application/json',
                    'X-Peer-Secret': Config.PEER_SYNC_SECRET,
                }
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status >= 300:
                    print(f"[SIPMAN] Peer {peer_url} sync {endpoint} → {resp.status}", flush=True)
        except urllib.error.URLError as e:
            print(f"[SIPMAN] Peer {peer_url} unreachable: {e}", flush=True)
        except Exception as e:
            print(f"[SIPMAN] Peer sync error {peer_url}: {e}", flush=True)


def _get_peer_urls():
    """Read peer list from SQLite + env, deduplicated."""
    from app.database import _admin_conn
    urls = set(Config.PEER_NODES)
    try:
        conn = _admin_conn()
        rows = conn.execute("SELECT url FROM peers WHERE is_active = 1").fetchall()
        conn.close()
        for r in rows:
            urls.add(r['url'])
    except Exception:
        pass
    return list(urls)


# ============================================================
# Sync handler functions (called by /sync/* routes)
# ============================================================

def sync_user(data):
    """Create/update a subscriber from peer payload."""
    username = data.get('username')
    domain = data.get('domain', Config.SIP_DOMAIN)
    password = data.get('password')
    email = data.get('email', '')
    ha1 = data.get('ha1') or (compute_ha1(username, domain, password) if password else None)
    rpid = data.get('rpid', f'extension_{username}@{domain.split(".")[-2] if "." in domain else "local"}')

    if not username or not ha1:
        return False, "username and ha1 (or password) required"

    existing = db_query("SELECT id FROM subscriber WHERE username=%s AND domain=%s", (username, domain))
    if existing:
        db_execute(
            "UPDATE subscriber SET ha1=%s, password=%s, email_address=%s WHERE id=%s",
            (ha1, password or '', email, existing[0]['id'])
        )
    else:
        db_execute(
            "INSERT INTO subscriber (username, domain, password, ha1, email_address, rpid) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (username, domain, password or '', ha1, email, rpid)
        )
    return True, "synced"


def sync_domain(data):
    """Create/update a domain from peer payload."""
    domain = data.get('domain')
    did = data.get('did', domain)
    if not domain:
        return False, "domain required"
    existing = db_query("SELECT id FROM domain WHERE domain=%s", (domain,))
    if existing:
        db_execute("UPDATE domain SET did=%s WHERE id=%s", (did, existing[0]['id']))
    else:
        db_execute("INSERT INTO domain (domain, did) VALUES (%s, %s)", (domain, did))
    return True, "synced"


def sync_gateway(data):
    """Create/update a dispatcher entry from peer payload."""
    dest = data.get('destination')
    if not dest:
        return False, "destination required"
    setid = data.get('setid', 1)
    description = data.get('description', '')
    attrs = data.get('attrs', '')
    flags = data.get('flags', 0)

    existing = db_query("SELECT id FROM dispatcher WHERE destination=%s", (dest,))
    if existing:
        db_execute(
            "UPDATE dispatcher SET setid=%s, description=%s, attrs=%s, flags=%s WHERE id=%s",
            (setid, description, attrs, flags, existing[0]['id'])
        )
    else:
        db_execute(
            "INSERT INTO dispatcher (setid, destination, flags, description, attrs) "
            "VALUES (%s, %s, %s, %s, %s)",
            (setid, dest, flags, description, attrs)
        )
    return True, "synced"


def sync_delete(table, match_field, match_value):
    """Delete a row from a Kamailio table by a single match field."""
    # Whitelist tables to prevent injection
    allowed = {'subscriber', 'domain', 'dispatcher'}
    if table not in allowed:
        return False, "table not allowed"
    db_execute(f"DELETE FROM {table} WHERE {match_field}=%s", (match_value,))
    return True, "deleted"


def full_sync_to_peers():
    """
    Push the entire local subscriber/domain/dispatcher dataset to all peers.
    Useful for initial setup or recovery.
    """
    if not Config.PEER_SYNC_ENABLED:
        return {"error": "peer sync disabled"}

    users = db_query("SELECT username, domain, password, ha1, email_address FROM subscriber")
    domains = db_query("SELECT domain, did FROM domain")
    gateways = db_query("SELECT setid, destination, description, attrs, flags FROM dispatcher")

    payload = {
        'users': users,
        'domains': domains,
        'gateways': gateways,
        'source_cluster': Config.CLUSTER_ID,
    }
    replicate_to_peers('/sync/full', 'POST', payload)
    return {"synced": True, "users": len(users), "domains": len(domains), "gateways": len(gateways)}


def receive_full_sync(data):
    """Process a full-sync payload from a peer."""
    count = 0
    for u in data.get('users', []):
        ok, _ = sync_user(u)
        if ok: count += 1
    for d in data.get('domains', []):
        sync_domain(d)
    for g in data.get('gateways', []):
        sync_gateway(g)
    return {"received": count}
