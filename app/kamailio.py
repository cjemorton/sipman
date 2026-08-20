"""
Kamailio control interface (kamcmd) and process utilities.
"""

import json
import subprocess
import socket

from app.config import Config


def kamcmd(command):
    """Run a kamcmd command, return stripped stdout (string)."""
    try:
        r = subprocess.run(
            [Config.KAMCMD_CMD, '-f', Config.KAMCMD_SOCKET, command],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return r.stdout.strip()
        return f"Error: {r.stderr.strip()}"
    except Exception as e:
        return f"Error: {e}"


def kamcmd_json(command):
    """Run kamcmd, parse JSON output."""
    try:
        r = subprocess.run(
            [Config.KAMCMD_CMD, '-f', Config.KAMCMD_SOCKET, command],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                return {"raw": r.stdout.strip()}
        return {"error": r.stderr.strip()}
    except Exception as e:
        return {"error": str(e)}


def check_process(name):
    """Check if a named process is running via pgrep.

    Uses substring match (pgrep without -x) because on Alpine/BusyBox
    pgrep -x matches the full process comm name (limited to 15 chars and
    may include the binary path), which fails for processes started as
    /usr/sbin/kamailio or /usr/bin/rtpengine.
    """
    try:
        r = subprocess.run(['pgrep', name], capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def check_rtpengine():
    """Ping RTPEngine control socket (UDP)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.sendto(b"ping\n", (Config.RTPENGINE_HOST, Config.RTPENGINE_PORT))
        s.close()
        return True, "Responsive"
    except Exception as e:
        return False, f"Unreachable: {e}"


def system_status():
    """Return a dict of service health for the cluster endpoint."""
    from app.database import check_mariadb
    db_ok, _ = check_mariadb()
    rtp_ok, _ = check_rtpengine()
    return {
        'kamailio_running': check_process('kamailio'),
        'rtpengine_running': rtp_ok,
        'mariadb_running': check_process('mariadbd') or check_process('mysqld'),
        'nginx_running': check_process('gunicorn'),  # API server (no nginx in this image)
        'db_connected': db_ok,
    }
