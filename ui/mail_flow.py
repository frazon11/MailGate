import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError

from flask import Blueprint, Response, redirect, render_template_string, request, url_for

from activity_log import CONFIG_DIR, _logs
from auth_store import verify_admin

bp = Blueprint("mail_flow", __name__)
CONTROL_DIR = Path(os.environ.get("FETCH_NOW_CONTROL_PATH", "/data/config/fetch-now"))
EVENT_FILE = CONTROL_DIR / "mail-flow.jsonl"
REQUEST_FILE = CONTROL_DIR / "fetch-now.request"
STATUS_FILE = CONTROL_DIR / "fetcher-status.json"

STYLE = """
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0f172a;color:#e5e7eb;font-family:system-ui,sans-serif}a{color:#93c5fd}header{background:#111827;border-bottom:1px solid #334155}header .wrap{max-width:1380px;margin:auto;padding:18px 22px;display:flex;align-items:center;justify-content:space-between;gap:20px}.brand{font-size:1.55rem;font-weight:750}.version{font-size:.78rem;color:#94a3b8}nav{display:flex;flex-wrap:wrap;gap:8px}nav a{padding:8px 11px;border-radius:7px;text-decoration:none;color:#cbd5e1}nav a.active,nav a:hover{background:#2563eb;color:#fff}main{max-width:1380px;margin:24px auto;padding:0 22px}.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metric{background:#111827;border-radius:9px;padding:12px}.metric strong{display:block;margin-top:4px}.muted{color:#94a3b8}.good{color:#86efac}.warn{color:#fde68a}.bad{color:#fca5a5}.error{background:#991b1b;padding:11px 13px;border-radius:8px}button,.button{display:inline-block;background:#2563eb;color:#fff;border:0;border-radius:7px;padding:9px 14px;text-decoration:none;cursor:pointer}.secondary{background:#475569}.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #334155;vertical-align:top}code{background:#0f172a;border-radius:5px;padding:2px 5px}.badge{display:inline-block;border-radius:999px;padding:3px 8px;background:#334155;font-size:.78rem}.badge.good{background:#065f46;color:#fff}.badge.warn{background:#92400e;color:#fff}.badge.bad{background:#991b1b;color:#fff}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}header .wrap{align-items:flex-start;flex-direction:column}table{display:block;overflow:auto}}@media(max-width:600px){.grid{grid-template-columns:1fr}}
"""

HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MailGate - Mail Flow</title><style>""" + STYLE + """</style>{% if refresh %}<meta http-equiv="refresh" content="{{ refresh }}">{% endif %}</head><body>
<header><div class="wrap"><div class="brand">MailGate <span class="version">v{{ version }} · build {{ build }}</span></div><nav><a href="/">Dashboard</a><a href="/accounts">Accounts & Delivery</a><a href="/spam">Spam Protection</a><a href="/antivirus">Antivirus</a><a class="active" href="/mail-flow">Mail Flow</a><a href="/activity">System Log</a><a href="/security">Security / Profile</a></nav></div></header>
<main><h1>Mail Flow</h1><p class="muted">Structured events written by the dedicated MailGate fetcher, plus delivery events detected in the mailserver log.</p>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<div class="card"><div class="actions"><form method="post" action="/mail-flow/fetch-now"><button type="submit">Fetch mail now</button></form><a class="button secondary" href="/mail-flow">Refresh</a><a class="button secondary" href="/activity">Open system log</a><span class="muted">Fetcher: {{ status.state }} · {{ status.message }} · {{ status.timestamp }}</span></div></div>
<div class="grid"><div class="metric"><span class="muted">Poll runs</span><strong>{{ counts.polls }}</strong></div><div class="metric"><span class="muted">Messages fetched</span><strong>{{ counts.fetched }}</strong></div><div class="metric"><span class="muted">SMTP accepted</span><strong class="good">{{ counts.accepted }}</strong></div><div class="metric"><span class="muted">Failures</span><strong class="bad">{{ counts.failed }}</strong></div></div>
<div class="card"><h2>Mailbox and message audit trail</h2>{% if events %}<table><thead><tr><th>Time</th><th>Account / folder</th><th>Stage</th><th>Message</th><th>Result</th></tr></thead><tbody>{% for e in events %}<tr><td>{{ e.time }}</td><td>{{ e.account or '—' }}{% if e.folder %}<br><code>{{ e.folder }}</code>{% endif %}{% if e.host %}<br><span class="muted">{{ e.host }}</span>{% endif %}</td><td>{{ e.label }}{% if e.reason %}<br><span class="muted">{{ e.reason }}</span>{% endif %}</td><td>{% if e.subject %}<strong>{{ e.subject }}</strong><br>{% endif %}{% if e.sender %}{{ e.sender }}<br>{% endif %}{% if e.recipient %}<span class="muted">→ {{ e.recipient }}</span><br>{% endif %}{% if e.remote_id %}<code>{{ e.remote_id }}</code>{% endif %}{% if e.messages != '' %}<span class="muted">Messages: {{ e.messages }}</span>{% endif %}</td><td><span class="badge {{ e.css }}">{{ e.result }}</span>{% if e.detail %}<br><span class="muted">{{ e.detail }}</span>{% endif %}</td></tr>{% endfor %}</tbody></table>{% else %}<p>No structured fetcher events exist yet. Rebuild and start <code>mailgate-fetcher</code>.</p>{% endif %}</div>
</main></body></html>"""

LABELS = {
    "fetcher_started": "Fetcher started",
    "poll_started": "Poll started",
    "mailbox_connect": "Connect to mailbox",
    "mailbox_login": "Mailbox login",
    "folder_check": "Check folder",
    "messages_found": "Messages found",
    "message_fetched": "Message downloaded",
    "smtp_submit_start": "Submit to MailGate SMTP",
    "smtp_accepted": "Accepted by MailGate SMTP",
    "source_retained": "Source retained",
    "source_deleted": "Deleted from provider",
    "poll_finished": "Poll finished",
    "account_error": "Account failure",
    "configuration_error": "Configuration failure",
}


def _auth_ok():
    auth = request.authorization
    return bool(auth and verify_admin(CONFIG_DIR, auth.username, auth.password))


@bp.before_request
def require_auth():
    if not _auth_ok():
        return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="MailGate"'})


def read_status():
    try:
        value = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {"state": "unknown", "message": "No fetcher status yet", "timestamp": "—"}


def read_events(limit=1000):
    try:
        lines = EVENT_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    events = []
    for line in reversed(lines):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = str(raw.get("result", "unknown"))
        css = "bad" if result in {"failed", "error"} else ("warn" if result in {"started", "unknown"} else "good")
        events.append({
            "time": raw.get("time", ""), "account": raw.get("account", ""), "folder": raw.get("folder", ""),
            "host": raw.get("host", ""), "label": LABELS.get(raw.get("event"), raw.get("event", "Event")),
            "reason": raw.get("reason", ""), "subject": raw.get("subject", ""), "sender": raw.get("sender", ""),
            "recipient": raw.get("recipient", ""), "remote_id": raw.get("remote_id", ""),
            "messages": raw.get("messages", ""), "result": result, "css": css, "detail": raw.get("detail", ""),
            "event": raw.get("event", ""),
        })
    return events


@bp.post("/mail-flow/fetch-now")
def fetch_now():
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    REQUEST_FILE.write_text("fetch now\n", encoding="utf-8")
    return redirect(url_for("mail_flow.mail_flow"))


@bp.get("/mail-flow")
def mail_flow():
    try:
        refresh = int(request.args.get("refresh", "15"))
    except ValueError:
        refresh = 15
    if refresh not in {0, 5, 15, 30, 60}:
        refresh = 15
    events = read_events()
    counts = {
        "polls": sum(1 for e in events if e["event"] == "poll_finished"),
        "fetched": sum(1 for e in events if e["event"] == "message_fetched"),
        "accepted": sum(1 for e in events if e["event"] == "smtp_accepted"),
        "failed": sum(1 for e in events if e["result"] in {"failed", "error"}),
    }
    return render_template_string(
        HTML,
        version=os.environ.get("MAILGATE_VERSION", "0.4.0"),
        build=os.environ.get("MAILGATE_BUILD", "dev"),
        events=events,
        counts=counts,
        status=read_status(),
        error="",
        refresh=refresh,
    )
