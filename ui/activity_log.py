import json
import os
import struct
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from flask import Blueprint, Response, render_template_string, request

from auth_store import verify_admin

bp = Blueprint("activity_log", __name__)
CONFIG_DIR = Path(os.environ.get("CONFIG_PATH", "/data/config"))
DOCKER_API_URL = os.environ.get("DOCKER_API_URL", "http://dockerproxy:2375").rstrip("/")
MAILSERVER_CONTAINER = os.environ.get("MAILSERVER_CONTAINER", "mailgate-mailserver")

STYLE = """
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0f172a;color:#e5e7eb;font-family:system-ui,sans-serif}a{color:#93c5fd}header{background:#111827;border-bottom:1px solid #334155}header .wrap{max-width:1280px;margin:auto;padding:18px 22px;display:flex;align-items:center;justify-content:space-between;gap:20px}.brand{font-size:1.55rem;font-weight:750}.version{font-size:.78rem;color:#94a3b8;font-weight:500}nav{display:flex;flex-wrap:wrap;gap:8px}nav a{padding:8px 11px;border-radius:7px;text-decoration:none;color:#cbd5e1}nav a.active,nav a:hover{background:#2563eb;color:white}main{max-width:1280px;margin:24px auto;padding:0 22px}.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metric{background:#111827;border-radius:9px;padding:12px}.metric strong{display:block;margin-top:4px}.muted{color:#94a3b8}.error{background:#991b1b;padding:11px 13px;border-radius:8px}.good{color:#6ee7b7}.bad{color:#fca5a5}input,select{width:100%;margin-top:5px;background:#0f172a;color:#e5e7eb;border:1px solid #475569;border-radius:7px;padding:9px}label{display:block}button,.button{display:inline-block;background:#2563eb;color:#fff;border:0;border-radius:7px;padding:9px 14px;text-decoration:none;cursor:pointer}.secondary{background:#475569}.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:end}.log{background:#020617;border:1px solid #334155;border-radius:9px;padding:14px;white-space:pre-wrap;overflow:auto;max-height:68vh;font:13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}.line-error{color:#fca5a5}.line-warn{color:#fde68a}.line-ok{color:#86efac}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}header .wrap{align-items:flex-start;flex-direction:column}}@media(max-width:600px){.grid{grid-template-columns:1fr}}
"""

HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MailGate - Activity Log</title><style>""" + STYLE + """</style>{% if auto_refresh %}<meta http-equiv="refresh" content="{{ auto_refresh }}">{% endif %}</head><body>
<header><div class="wrap"><div class="brand">MailGate <span class="version">v{{ version }} · build {{ build }}</span></div><nav><a href="/">Dashboard</a><a href="/accounts">Accounts & Delivery</a><a href="/spam">Spam Protection</a><a href="/antivirus">Antivirus</a><a class="active" href="/activity">Activity Log</a><a href="/security">Security / Profile</a></nav></div></header>
<main><h1>Activity Log</h1>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<div class="grid"><div class="metric"><span class="muted">Container</span><strong>{{ status.name }}</strong></div><div class="metric"><span class="muted">State</span><strong class="{{ 'good' if status.running else 'bad' }}">{{ status.state }}</strong></div><div class="metric"><span class="muted">Health</span><strong>{{ status.health }}</strong></div><div class="metric"><span class="muted">Started</span><strong>{{ status.started }}</strong></div></div>
<div class="card"><form method="get"><div class="grid"><label>Lines<select name="tail">{% for n in [100,500,1000,5000] %}<option value="{{ n }}" {% if tail==n %}selected{% endif %}>{{ n }}</option>{% endfor %}</select></label><label>Filter<input name="q" value="{{ query }}" placeholder="fetchmail, rspamd, clamav, error..."></label><label>Auto-refresh<select name="refresh"><option value="0">Off</option>{% for n in [5,15,30,60] %}<option value="{{ n }}" {% if auto_refresh==n %}selected{% endif %}>{{ n }} seconds</option>{% endfor %}</select></label><div class="actions"><button type="submit">Refresh</button><a class="button secondary" href="{{ download_url }}">Download snapshot</a></div></div></form><p class="muted">Shows the real stdout/stderr stream from <code>{{ status.name }}</code>. Filtering is case-insensitive and applies after the selected tail is retrieved.</p></div>
<div class="card"><div class="log">{% if lines %}{% for line in lines %}<span class="{{ line.css }}">{{ line.text }}</span>\n{% endfor %}{% else %}No matching log entries were returned.{% endif %}</div></div>
</main></body></html>"""


def _auth_ok():
    auth = request.authorization
    return bool(auth and verify_admin(CONFIG_DIR, auth.username, auth.password))


@bp.before_request
def require_auth():
    if not _auth_ok():
        return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="MailGate"'})


def _api_get(path, timeout=15):
    req = Request(f"{DOCKER_API_URL}{path}", method="GET", headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def _decode_log_stream(payload):
    # Docker multiplexes stdout/stderr with an 8-byte header when TTY is disabled.
    output = []
    offset = 0
    while offset + 8 <= len(payload):
        stream_type = payload[offset]
        size = struct.unpack(">I", payload[offset + 4:offset + 8])[0]
        end = offset + 8 + size
        if stream_type not in (0, 1, 2) or end > len(payload):
            break
        output.append(payload[offset + 8:end])
        offset = end
    if output and offset == len(payload):
        payload = b"".join(output)
    return payload.decode("utf-8", errors="replace")


def _container_status():
    raw, _ = _api_get(f"/containers/{quote(MAILSERVER_CONTAINER, safe='')}/json")
    data = json.loads(raw.decode("utf-8"))
    state = data.get("State", {})
    health = state.get("Health", {}).get("Status", "not configured")
    return {
        "name": data.get("Name", "/" + MAILSERVER_CONTAINER).lstrip("/"),
        "state": state.get("Status", "unknown"),
        "running": bool(state.get("Running")),
        "health": health,
        "started": state.get("StartedAt", "unknown").replace("T", " ").replace("Z", " UTC"),
    }


def _logs(tail):
    params = urlencode({"stdout": 1, "stderr": 1, "timestamps": 1, "tail": tail})
    raw, _ = _api_get(f"/containers/{quote(MAILSERVER_CONTAINER, safe='')}/logs?{params}", timeout=30)
    return _decode_log_stream(raw)


def _classify(text):
    lower = text.lower()
    if any(token in lower for token in (" error", "fatal", "panic", "failed", "denied", "reject", "virus", "malware")):
        return "line-error"
    if any(token in lower for token in ("warning", " warn", "temporary", "deferred", "timeout")):
        return "line-warn"
    if any(token in lower for token in ("success", "accepted", "delivered", "clean", "started", "ready")):
        return "line-ok"
    return ""


@bp.get("/activity")
def activity():
    try:
        tail = int(request.args.get("tail", "500"))
    except ValueError:
        tail = 500
    if tail not in {100, 500, 1000, 5000}:
        tail = 500
    try:
        refresh = int(request.args.get("refresh", "0"))
    except ValueError:
        refresh = 0
    if refresh not in {0, 5, 15, 30, 60}:
        refresh = 0
    query = request.args.get("q", "").strip()
    error = ""
    status = {"name": MAILSERVER_CONTAINER, "state": "unavailable", "running": False, "health": "unavailable", "started": "unavailable"}
    text = ""
    try:
        status = _container_status()
        text = _logs(tail)
    except HTTPError as exc:
        error = f"Docker log proxy returned HTTP {exc.code}: {exc.reason}"
    except URLError as exc:
        error = f"Cannot reach the restricted Docker log proxy: {exc.reason}"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        error = f"Could not read container status/logs: {exc}"

    raw_lines = text.splitlines()
    if query:
        needle = query.casefold()
        raw_lines = [line for line in raw_lines if needle in line.casefold()]
    lines = [{"text": line, "css": _classify(line)} for line in raw_lines]
    download_url = "/activity/download?" + urlencode({"tail": tail, "q": query})
    return render_template_string(
        HTML,
        version=os.environ.get("MAILGATE_VERSION", "0.2.2"),
        build=os.environ.get("MAILGATE_BUILD", "dev"),
        status=status,
        lines=lines,
        error=error,
        tail=tail,
        query=query,
        auto_refresh=refresh,
        download_url=download_url,
    )


@bp.get("/activity/download")
def download():
    try:
        tail = int(request.args.get("tail", "5000"))
    except ValueError:
        tail = 5000
    tail = min(max(tail, 1), 10000)
    query = request.args.get("q", "").strip()
    try:
        text = _logs(tail)
        if query:
            needle = query.casefold()
            text = "\n".join(line for line in text.splitlines() if needle in line.casefold()) + "\n"
    except Exception as exc:
        text = f"Unable to retrieve MailGate logs: {exc}\n"
    headers = {"Content-Disposition": 'attachment; filename="mailgate-activity.log"'}
    return Response(text, mimetype="text/plain; charset=utf-8", headers=headers)
