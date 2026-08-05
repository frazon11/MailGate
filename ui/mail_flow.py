import json
import os
import re
from collections import OrderedDict
from pathlib import Path
from urllib.error import HTTPError, URLError

from flask import Blueprint, Response, render_template_string, request

from activity_log import CONFIG_DIR, _logs
from auth_store import verify_admin

bp = Blueprint("mail_flow", __name__)
POLL_EVENTS_FILE = Path(os.environ.get("FETCH_NOW_CONTROL_PATH", "/data/config/fetch-now")) / "poll-events.jsonl"

TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\S+)\s+(.*)$")
FROM_RE = re.compile(r"from=<([^>]*)>")
TO_RE = re.compile(r"to=<([^>]*)>")
SUBJECT_RE = re.compile(r"subject[=:]\s*[\"']?([^\"']+)", re.I)
SCORE_RE = re.compile(r"(?:score|metric)[=: ]+(-?\d+(?:\.\d+)?)", re.I)
FOLDER_RE = re.compile(r"(?:folder|mailbox)[ =:\"']+([^\"',;]+)", re.I)
COUNT_RE = re.compile(r"(?:message count|messages?)[ =:]+(\d+)", re.I)

STYLE = """
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0f172a;color:#e5e7eb;font-family:system-ui,sans-serif}a{color:#93c5fd}header{background:#111827;border-bottom:1px solid #334155}header .wrap{max-width:1380px;margin:auto;padding:18px 22px;display:flex;align-items:center;justify-content:space-between;gap:20px}.brand{font-size:1.55rem;font-weight:750}.version{font-size:.78rem;color:#94a3b8}nav{display:flex;flex-wrap:wrap;gap:8px}nav a{padding:8px 11px;border-radius:7px;text-decoration:none;color:#cbd5e1}nav a.active,nav a:hover{background:#2563eb;color:white}main{max-width:1380px;margin:24px auto;padding:0 22px}.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metric{background:#111827;border-radius:9px;padding:12px}.metric strong{display:block;margin-top:4px}.muted{color:#94a3b8}.error{background:#991b1b;padding:11px 13px;border-radius:8px}.good{color:#86efac}.warn{color:#fde68a}.bad{color:#fca5a5}input,select{width:100%;margin-top:5px;background:#0f172a;color:#e5e7eb;border:1px solid #475569;border-radius:7px;padding:9px}label{display:block}button,.button{display:inline-block;background:#2563eb;color:#fff;border:0;border-radius:7px;padding:9px 14px;text-decoration:none;cursor:pointer}.secondary{background:#475569}.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:end}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #334155;vertical-align:top}code{background:#0f172a;border-radius:5px;padding:2px 5px}.steps{display:flex;gap:5px;flex-wrap:wrap}.step{font-size:.78rem;padding:3px 7px;border-radius:999px;background:#334155}.step.ok{background:#065f46}.step.warn{background:#92400e}.step.bad{background:#991b1b}.details{font-size:.82rem;color:#94a3b8;white-space:pre-wrap;max-width:520px}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}header .wrap{align-items:flex-start;flex-direction:column}table{display:block;overflow:auto}}@media(max-width:600px){.grid{grid-template-columns:1fr}}
"""

HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MailGate - Mail Flow</title><style>""" + STYLE + """</style>{% if refresh %}<meta http-equiv="refresh" content="{{ refresh }}">{% endif %}</head><body>
<header><div class="wrap"><div class="brand">MailGate <span class="version">v{{ version }} · build {{ build }}</span></div><nav><a href="/">Dashboard</a><a href="/accounts">Accounts & Delivery</a><a href="/spam">Spam Protection</a><a href="/antivirus">Antivirus</a><a class="active" href="/mail-flow">Mail Flow</a><a href="/activity">System Log</a><a href="/security">Security / Profile</a></nav></div></header>
<main><h1>Mail Flow</h1><p class="muted">Operational message processing only. Startup, supervisor and container noise is excluded.</p>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<div class="grid"><div class="metric"><span class="muted">Mailbox checks</span><strong>{{ counts.checks }}</strong></div><div class="metric"><span class="muted">Messages detected</span><strong>{{ counts.detected }}</strong></div><div class="metric"><span class="muted">Delivered</span><strong class="good">{{ counts.delivered }}</strong></div><div class="metric"><span class="muted">Rejected / failed</span><strong class="bad">{{ counts.failed }}</strong></div></div>
<div class="card"><form method="get"><div class="grid"><label>Raw lines analysed<select name="tail">{% for n in [500,1000,5000,10000] %}<option value="{{ n }}" {% if tail==n %}selected{% endif %}>{{ n }}</option>{% endfor %}</select></label><label>Filter<input name="q" value="{{ query }}" placeholder="sender, recipient, queue ID, folder..."></label><label>Auto-refresh<select name="refresh"><option value="0">Off</option>{% for n in [5,15,30,60] %}<option value="{{ n }}" {% if refresh==n %}selected{% endif %}>{{ n }} seconds</option>{% endfor %}</select></label><div class="actions"><button>Refresh</button><button type="submit" form="fetch-now-form">Fetch mail now</button><a class="button secondary" href="/activity">Open technical system log</a></div></div></form><form id="fetch-now-form" method="post" action="/accounts/fetch-now"></form></div>
<div class="card"><h2>Message processing</h2>{% if messages %}<table><thead><tr><th>Last event</th><th>Message</th><th>Processing</th><th>Result</th></tr></thead><tbody>{% for m in messages %}<tr><td>{{ m.time }}</td><td>{% if m.queue_id %}<code>{{ m.queue_id }}</code><br>{% endif %}<strong>{{ m.sender or 'Unknown sender' }}</strong><br><span class="muted">→ {{ m.recipient or 'Unknown recipient' }}</span>{% if m.subject %}<br>{{ m.subject }}{% endif %}</td><td><div class="steps">{% for s in m.steps %}<span class="step {{ s.css }}">{{ s.label }}</span>{% endfor %}</div>{% if m.spam_score %}<div class="muted">Spam score: {{ m.spam_score }}</div>{% endif %}<details><summary class="muted">Event details</summary><div class="details">{{ m.details }}</div></details></td><td><strong class="{{ m.result_css }}">{{ m.result }}</strong></td></tr>{% endfor %}</tbody></table>{% else %}<p>No message-processing events were identified in the selected log range.</p>{% endif %}</div>
<div class="card"><h2>Mailbox polling</h2>{% if polls %}<table><thead><tr><th>Time</th><th>Source</th><th>Event</th><th>Processes/messages</th></tr></thead><tbody>{% for p in polls %}<tr><td>{{ p.time }}</td><td>{{ p.mailbox }}</td><td class="{{ p.css }}">{{ p.event }}</td><td>{{ p.count }}</td></tr>{% endfor %}</tbody></table>{% else %}<p>No mailbox polling attempts have been recorded. Rebuild and restart <code>mailgate-fetchtrigger</code>, then press <strong>Fetch mail now</strong>.</p>{% endif %}</div>
</main></body></html>"""


def _auth_ok():
    auth = request.authorization
    return bool(auth and verify_admin(CONFIG_DIR, auth.username, auth.password))


@bp.before_request
def require_auth():
    if not _auth_ok():
        return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="MailGate"'})


def _split(line):
    match = TIMESTAMP_RE.match(line)
    return (match.group(1), match.group(2)) if match else ("", line)


def _queue_id(text):
    match = re.search(r"\b([A-F0-9]{7,16}):", text)
    return match.group(1) if match else None


def _event_step(text):
    lower = text.lower()
    if "fetchmail" in lower and any(x in lower for x in ("reading message", "fetching message", "message ")):
        return ("Fetched", "ok")
    if "rspamd" in lower or "milter" in lower:
        return ("Spam checked", "warn" if any(x in lower for x in ("reject", "spam")) else "ok")
    if "clam" in lower or "virus" in lower or "malware" in lower:
        blocked = any(x in lower for x in ("virus", "infected", "malware", "reject")) and "clean" not in lower
        return ("AV blocked", "bad") if blocked else ("AV clean", "ok")
    if "postfix" in lower:
        if "status=sent" in lower:
            return ("Delivered", "ok")
        if "status=deferred" in lower:
            return ("Deferred", "warn")
        if any(x in lower for x in ("status=bounced", "reject", "discard")):
            return ("Rejected", "bad")
        if "cleanup" in lower or "smtpd" in lower:
            return ("Accepted", "ok")
    return None


def _structured_polls():
    rows = []
    try:
        lines = POLL_EVENTS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines[-500:]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        state = event.get("state", "unknown")
        rows.append({
            "time": event.get("timestamp", ""),
            "mailbox": "Startup poll" if event.get("source") == "startup" else "Manual poll",
            "event": event.get("message", state),
            "count": event.get("process_count", 0),
            "css": "good" if state == "triggered" else ("bad" if state == "failed" else "warn"),
        })
    rows.reverse()
    return rows


def parse_mail_flow(text):
    messages = OrderedDict()
    polls = _structured_polls()
    unkeyed = 0
    for raw in text.splitlines():
        timestamp, line = _split(raw)
        lower = line.lower()
        if "fetchmail" in lower:
            poll_event = None
            if any(x in lower for x in ("authorization succeeded", "authenticated", "login")):
                poll_event = "Mailbox login successful"
            elif any(x in lower for x in ("polling", "querying", "selecting", "checking")):
                poll_event = "Checking mailbox"
            elif any(x in lower for x in ("no mail", "no messages")):
                poll_event = "No new messages"
            if poll_event:
                folder_match = FOLDER_RE.search(line)
                count_match = COUNT_RE.search(line)
                polls.append({"time": timestamp, "mailbox": folder_match.group(1).strip() if folder_match else "Provider mailbox", "event": poll_event, "count": count_match.group(1) if count_match else "—", "css": "good"})

        step = _event_step(line)
        if not step:
            continue
        queue_id = _queue_id(line)
        if queue_id:
            key = queue_id
        else:
            unkeyed += 1
            key = f"event-{unkeyed}"
        event = messages.setdefault(key, {"queue_id": queue_id, "time": timestamp, "sender": "", "recipient": "", "subject": "", "spam_score": "", "steps": [], "details": [], "result": "Processing", "result_css": "warn"})
        event["time"] = timestamp or event["time"]
        for regex, field in ((FROM_RE, "sender"), (TO_RE, "recipient"), (SUBJECT_RE, "subject"), (SCORE_RE, "spam_score")):
            match = regex.search(line)
            if match:
                event[field] = match.group(1).strip()
        if not any(existing["label"] == step[0] for existing in event["steps"]):
            event["steps"].append({"label": step[0], "css": step[1]})
        event["details"].append(line)
        if step[0] == "Delivered":
            event["result"], event["result_css"] = "Delivered to Exchange", "good"
        elif step[0] in {"Rejected", "AV blocked"}:
            event["result"], event["result_css"] = step[0], "bad"
        elif step[0] == "Deferred":
            event["result"], event["result_css"] = "Deferred", "warn"
        elif event["result"] == "Processing":
            event["result"] = step[0]

    rows = []
    for event in messages.values():
        event["details"] = "\n".join(event["details"])
        rows.append(event)
    rows.reverse()
    counts = {
        "checks": sum(1 for p in polls if p.get("event")),
        "detected": sum(1 for row in rows if any(s["label"] == "Fetched" for s in row["steps"])),
        "delivered": sum(1 for row in rows if row["result"] == "Delivered to Exchange"),
        "failed": sum(1 for row in rows if row["result_css"] == "bad"),
    }
    return rows, polls, counts


@bp.get("/mail-flow")
def mail_flow():
    try:
        tail = int(request.args.get("tail", "5000"))
    except ValueError:
        tail = 5000
    if tail not in {500, 1000, 5000, 10000}:
        tail = 5000
    try:
        refresh = int(request.args.get("refresh", "15"))
    except ValueError:
        refresh = 15
    if refresh not in {0, 5, 15, 30, 60}:
        refresh = 15
    query = request.args.get("q", "").strip()
    error = ""
    text = ""
    try:
        text = _logs(tail)
    except HTTPError as exc:
        error = f"Log proxy returned HTTP {exc.code}: {exc.reason}"
    except URLError as exc:
        error = f"Cannot reach the log proxy: {exc.reason}"
    except OSError as exc:
        error = f"Could not read mailserver logs: {exc}"
    messages, polls, counts = parse_mail_flow(text)
    if query:
        needle = query.casefold()
        messages = [m for m in messages if needle in ((m["queue_id"] or "") + m["sender"] + m["recipient"] + m["subject"] + m["details"]).casefold()]
        polls = [p for p in polls if needle in (p["mailbox"] + " " + p["event"]).casefold()]
    return render_template_string(HTML, version=os.environ.get("MAILGATE_VERSION", "0.3.1"), build=os.environ.get("MAILGATE_BUILD", "dev"), messages=messages, polls=polls, counts=counts, error=error, tail=tail, query=query, refresh=refresh)
