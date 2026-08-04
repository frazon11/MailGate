import json
import os
import secrets
from functools import wraps
from pathlib import Path
from tempfile import NamedTemporaryFile

from flask import Flask, Response, flash, redirect, render_template_string, request, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

CONFIG_DIR = Path(os.environ.get("CONFIG_PATH", "/data/config"))
SETTINGS_FILE = CONFIG_DIR / "mailgate.json"
FETCHMAIL_FILE = CONFIG_DIR / "fetchmail.cf"

HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MailGate</title>
  <style>
    body{font-family:system-ui,sans-serif;background:#111827;color:#e5e7eb;margin:0}
    main{max-width:1100px;margin:32px auto;padding:0 20px}
    h1{margin-bottom:4px}.muted{color:#9ca3af}.card{background:#1f2937;border:1px solid #374151;border-radius:12px;padding:18px;margin:18px 0}
    table{width:100%;border-collapse:collapse}th,td{padding:10px;text-align:left;border-bottom:1px solid #374151}
    input,select{width:100%;box-sizing:border-box;background:#111827;color:#e5e7eb;border:1px solid #4b5563;border-radius:7px;padding:9px}
    .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.actions{display:flex;gap:10px;align-items:center}
    button,.button{background:#2563eb;color:white;border:0;border-radius:7px;padding:9px 14px;text-decoration:none;cursor:pointer}
    .danger{background:#b91c1c}.ok{background:#065f46;padding:10px;border-radius:7px}.warn{background:#92400e;padding:10px;border-radius:7px}
    code{background:#111827;padding:2px 5px;border-radius:4px}@media(max-width:750px){.grid{grid-template-columns:1fr}table{display:block;overflow:auto}}
  </style>
</head>
<body><main>
<h1>MailGate</h1>
<div class="muted">IMAP/POP3 retrieval, Rspamd and ClamAV scanning, then SMTP relay to Exchange.</div>
{% with messages = get_flashed_messages() %}{% for message in messages %}<p class="ok">{{ message }}</p>{% endfor %}{% endwith %}

<div class="card">
  <h2>Backend</h2>
  <div class="grid">
    <div><strong>Exchange target</strong><br><code>{{ exchange_host }}:{{ exchange_port }}</code></div>
    <div><strong>Fetch interval</strong><br><code>{{ poll_interval }} seconds</code></div>
  </div>
  <p class="muted">These values come from the Portainer stack environment. Mailbox changes are written to <code>fetchmail.cf</code> and detected by Docker Mailserver.</p>
</div>

<div class="card">
  <h2>Mailboxes</h2>
  {% if accounts %}
  <table><thead><tr><th>Provider</th><th>Login</th><th>Protocol</th><th>Exchange recipient</th><th>Source handling</th><th></th></tr></thead><tbody>
  {% for a in accounts %}<tr>
    <td>{{ a.host }}:{{ a.port }}</td><td>{{ a.username }}</td><td>{{ a.protocol|upper }} / TLS</td><td>{{ a.recipient }}</td>
    <td>{{ 'Keep copy' if a.keep else 'Delete after accepted' }}</td>
    <td><form method="post" action="{{ url_for('delete_account', index=loop.index0) }}"><button class="danger" type="submit">Delete</button></form></td>
  </tr>{% endfor %}</tbody></table>
  {% else %}<p class="warn">No provider mailboxes configured yet.</p>{% endif %}
</div>

<div class="card">
  <h2>Add mailbox</h2>
  <form method="post" action="{{ url_for('add_account') }}">
    <div class="grid">
      <label>IMAP/POP server<input required name="host" placeholder="imap.example.com"></label>
      <label>Port<input required name="port" type="number" value="993"></label>
      <label>Protocol<select name="protocol"><option value="imap">IMAP</option><option value="pop3">POP3</option></select></label>
      <label>Provider username<input required name="username" autocomplete="off"></label>
      <label>Provider password<input required name="password" type="password" autocomplete="new-password"></label>
      <label>Exchange recipient<input required name="recipient" type="email" placeholder="user@example.com"></label>
      <label><input style="width:auto" type="checkbox" name="keep" checked> Keep messages at provider</label>
    </div><p><button type="submit">Save and generate configuration</button></p>
  </form>
</div>

<div class="card">
  <h2>Generated configuration</h2>
  <p><code>{{ fetchmail_file }}</code></p>
  <pre style="white-space:pre-wrap;overflow:auto;background:#111827;padding:12px;border-radius:7px">{{ generated }}</pre>
</div>
</main></body></html>
"""


def requires_auth(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        user = os.environ.get("UI_USERNAME", "admin")
        password = os.environ.get("UI_PASSWORD", "change-me-now")
        if not auth or not secrets.compare_digest(auth.username, user) or not secrets.compare_digest(auth.password, password):
            return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="MailGate"'})
        return func(*args, **kwargs)
    return wrapped


def load_settings():
    if not SETTINGS_FILE.exists():
        return {"accounts": []}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("accounts"), list) else {"accounts": []}
    except (OSError, json.JSONDecodeError):
        return {"accounts": []}


def atomic_write(path: Path, content: str, mode: int = 0o600):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=CONFIG_DIR, delete=False) as handle:
        handle.write(content)
        temp_name = handle.name
    os.chmod(temp_name, mode)
    os.replace(temp_name, path)


def generate_fetchmail(accounts):
    lines = [
        "set no bouncemail",
        "set no spambounce",
        "set syslog",
        "defaults timeout 60",
        "",
    ]
    for account in accounts:
        keep_flag = "keep" if account.get("keep", True) else "no keep"
        protocol = account.get("protocol", "imap").lower()
        lines.extend([
            f"poll {json.dumps(account['host'])} protocol {protocol}",
            f"  port {int(account['port'])}",
            f"  user {json.dumps(account['username'])}",
            f"  password {json.dumps(account['password'])}",
            "  ssl",
            f"  {keep_flag}",
            f"  smtpname {json.dumps(account['recipient'])}",
            "  smtphost 127.0.0.1",
            "",
        ])
    return "\n".join(lines)


def save_settings(data):
    atomic_write(SETTINGS_FILE, json.dumps(data, indent=2) + "\n")
    atomic_write(FETCHMAIL_FILE, generate_fetchmail(data["accounts"]))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
@requires_auth
def index():
    settings = load_settings()
    generated = generate_fetchmail(settings["accounts"])
    return render_template_string(
        HTML,
        accounts=settings["accounts"],
        generated=generated,
        fetchmail_file=str(FETCHMAIL_FILE),
        exchange_host=os.environ.get("EXCHANGE_HOST", "not configured"),
        exchange_port=os.environ.get("EXCHANGE_PORT", "25"),
        poll_interval=os.environ.get("FETCHMAIL_POLL_INTERVAL", "60"),
    )


@app.post("/accounts")
@requires_auth
def add_account():
    settings = load_settings()
    try:
        port = int(request.form["port"])
        if not 1 <= port <= 65535:
            raise ValueError
    except (KeyError, ValueError):
        return "Invalid port", 400
    account = {
        "host": request.form.get("host", "").strip(),
        "port": port,
        "protocol": request.form.get("protocol", "imap").lower(),
        "username": request.form.get("username", "").strip(),
        "password": request.form.get("password", ""),
        "recipient": request.form.get("recipient", "").strip(),
        "keep": request.form.get("keep") == "on",
    }
    if account["protocol"] not in {"imap", "pop3"} or not all(account[k] for k in ("host", "username", "password", "recipient")):
        return "Missing or invalid values", 400
    settings["accounts"].append(account)
    save_settings(settings)
    flash("Mailbox saved. Docker Mailserver will detect the updated Fetchmail configuration.")
    return redirect(url_for("index"))


@app.post("/accounts/<int:index>/delete")
@requires_auth
def delete_account(index):
    settings = load_settings()
    if index < 0 or index >= len(settings["accounts"]):
        return "Mailbox not found", 404
    settings["accounts"].pop(index)
    save_settings(settings)
    flash("Mailbox removed and configuration regenerated.")
    return redirect(url_for("index"))
