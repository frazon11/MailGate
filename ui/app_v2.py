import json
import os
import secrets
from functools import wraps
from pathlib import Path
from tempfile import NamedTemporaryFile

from flask import Flask, Response, flash, redirect, render_template_string, request, url_for

from connection_tests import test_exchange, test_provider

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

CONFIG_DIR = Path(os.environ.get("CONFIG_PATH", "/data/config"))
SETTINGS_FILE = CONFIG_DIR / "mailgate.json"
FETCHMAIL_FILE = CONFIG_DIR / "fetchmail.cf"

HTML = r"""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MailGate</title><style>
body{font-family:system-ui,sans-serif;background:#111827;color:#e5e7eb;margin:0}main{max-width:1100px;margin:32px auto;padding:0 20px}
h1{margin-bottom:4px}.muted{color:#9ca3af}.card{background:#1f2937;border:1px solid #374151;border-radius:12px;padding:18px;margin:18px 0}
table{width:100%;border-collapse:collapse}th,td{padding:10px;text-align:left;border-bottom:1px solid #374151}
input,select{width:100%;box-sizing:border-box;background:#111827;color:#e5e7eb;border:1px solid #4b5563;border-radius:7px;padding:9px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button{background:#2563eb;color:white;border:0;border-radius:7px;padding:9px 14px;cursor:pointer}.secondary{background:#4b5563}.danger{background:#b91c1c}
.ok{background:#065f46;padding:10px;border-radius:7px}.error{background:#991b1b;padding:10px;border-radius:7px}.warn{background:#92400e;padding:10px;border-radius:7px}
code{background:#111827;padding:2px 5px;border-radius:4px}@media(max-width:750px){.grid{grid-template-columns:1fr}table{display:block;overflow:auto}}
</style></head><body><main>
<h1>MailGate</h1><div class="muted">IMAP/POP3 retrieval, Rspamd and ClamAV scanning, then SMTP relay to Exchange.</div>
{% with messages=get_flashed_messages(with_categories=true) %}{% for category,message in messages %}<p class="{{ 'error' if category=='error' else 'ok' }}">{{ message }}</p>{% endfor %}{% endwith %}
<div class="card"><h2>Backend</h2><div class="grid"><div><strong>Exchange target</strong><br><code>{{ exchange_host }}:{{ exchange_port }}</code></div><div><strong>Fetch interval</strong><br><code>{{ poll_interval }} seconds</code></div></div></div>
<div class="card"><h2>Mailboxes</h2>{% if accounts %}<table><thead><tr><th>Provider</th><th>Login</th><th>Protocol</th><th>Exchange recipient</th><th>Source handling</th><th></th></tr></thead><tbody>{% for a in accounts %}<tr><td>{{ a.host }}:{{ a.port }}</td><td>{{ a.username }}</td><td>{{ a.protocol|upper }} / TLS</td><td>{{ a.recipient }}</td><td>{{ 'Keep copy' if a.keep else 'Delete after accepted' }}</td><td><form method="post" action="{{ url_for('delete_account',index=loop.index0) }}"><button class="danger">Delete</button></form></td></tr>{% endfor %}</tbody></table>{% else %}<p class="warn">No provider mailboxes configured yet.</p>{% endif %}</div>
<div class="card"><h2>Add mailbox</h2><form method="post"><div class="grid">
<label>IMAP/POP server<input required name="host" value="{{ form.host }}" placeholder="imap.example.com"></label>
<label>Port<input required name="port" type="number" value="{{ form.port }}"></label>
<label>Protocol<select name="protocol"><option value="imap" {% if form.protocol=='imap' %}selected{% endif %}>IMAP</option><option value="pop3" {% if form.protocol=='pop3' %}selected{% endif %}>POP3</option></select></label>
<label>Provider username<input required name="username" value="{{ form.username }}" autocomplete="off"></label>
<label>Provider password<input required name="password" type="password" autocomplete="new-password"></label>
<label>Exchange recipient<input required name="recipient" type="email" value="{{ form.recipient }}" placeholder="user@example.com"></label>
<label><input style="width:auto" type="checkbox" name="keep" {% if form.keep %}checked{% endif %}> Keep messages at provider</label></div>
<p class="actions"><button class="secondary" formaction="{{ url_for('test_provider_route') }}">Test provider login</button><button class="secondary" formaction="{{ url_for('test_exchange_route') }}">Test Exchange recipient</button><button formaction="{{ url_for('add_account') }}">Save and generate configuration</button></p>
<p class="muted">The Exchange test validates SMTP connectivity and recipient acceptance using RCPT TO, then resets the transaction. It sends no message.</p></form></div>
<div class="card"><h2>Generated configuration</h2><p><code>{{ fetchmail_file }}</code></p><pre style="white-space:pre-wrap;overflow:auto;background:#111827;padding:12px;border-radius:7px">{{ generated }}</pre></div>
</main></body></html>"""


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


def atomic_write(path, content, mode=0o600):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=CONFIG_DIR, delete=False) as handle:
        handle.write(content)
        temp_name = handle.name
    os.chmod(temp_name, mode)
    os.replace(temp_name, path)


def generate_fetchmail(accounts):
    lines = ["set no bouncemail", "set no spambounce", "set syslog", "defaults timeout 60", ""]
    for account in accounts:
        lines.extend([
            f"poll {json.dumps(account['host'])} protocol {account['protocol']}",
            f"  port {int(account['port'])}",
            f"  user {json.dumps(account['username'])}",
            f"  password {json.dumps(account['password'])}",
            "  ssl",
            f"  {'keep' if account.get('keep', True) else 'no keep'}",
            f"  smtpname {json.dumps(account['recipient'])}",
            "  smtphost 127.0.0.1",
            "",
        ])
    return "\n".join(lines)


def save_settings(data):
    atomic_write(SETTINGS_FILE, json.dumps(data, indent=2) + "\n")
    atomic_write(FETCHMAIL_FILE, generate_fetchmail(data["accounts"]))


def parse_form(require_password=True):
    try:
        port = int(request.form.get("port", "0"))
    except ValueError as exc:
        raise ValueError("Provider port must be numeric.") from exc
    account = {
        "host": request.form.get("host", "").strip(), "port": port,
        "protocol": request.form.get("protocol", "imap").lower(),
        "username": request.form.get("username", "").strip(),
        "password": request.form.get("password", ""),
        "recipient": request.form.get("recipient", "").strip(),
        "keep": request.form.get("keep") == "on",
    }
    if not 1 <= port <= 65535 or account["protocol"] not in {"imap", "pop3"}:
        raise ValueError("Invalid provider protocol or port.")
    required = ("host", "username", "recipient") + (("password",) if require_password else ())
    if not all(account[k] for k in required):
        raise ValueError("All mailbox fields are required.")
    return account


def retained_form():
    return {"host": request.form.get("host", ""), "port": request.form.get("port", "993"), "protocol": request.form.get("protocol", "imap"), "username": request.form.get("username", ""), "recipient": request.form.get("recipient", ""), "keep": request.form.get("keep", "on") == "on"}


def render_page(form=None):
    settings = load_settings()
    return render_template_string(HTML, accounts=settings["accounts"], generated=generate_fetchmail(settings["accounts"]), fetchmail_file=str(FETCHMAIL_FILE), exchange_host=os.environ.get("EXCHANGE_HOST", "not configured"), exchange_port=os.environ.get("EXCHANGE_PORT", "25"), poll_interval=os.environ.get("FETCHMAIL_POLL_INTERVAL", "60"), form=form or {"host":"","port":"993","protocol":"imap","username":"","recipient":"","keep":True})


@app.get("/health")
def health(): return {"status": "ok"}

@app.get("/")
@requires_auth
def index(): return render_page()

@app.post("/accounts/test-provider")
@requires_auth
def test_provider_route():
    form = retained_form()
    try:
        a = parse_form()
        flash(test_provider(a["host"], a["port"], a["protocol"], a["username"], a["password"]), "success")
    except Exception as exc:
        flash(f"Provider test failed: {exc}", "error")
    return render_page(form)

@app.post("/accounts/test-exchange")
@requires_auth
def test_exchange_route():
    form = retained_form()
    try:
        recipient = request.form.get("recipient", "").strip()
        if not recipient: raise ValueError("Exchange recipient is required.")
        flash(test_exchange(recipient), "success")
    except Exception as exc:
        flash(f"Exchange test failed: {exc}", "error")
    return render_page(form)

@app.post("/accounts")
@requires_auth
def add_account():
    try:
        account = parse_form()
    except ValueError as exc:
        flash(str(exc), "error")
        return render_page(retained_form()), 400
    settings = load_settings(); settings["accounts"].append(account); save_settings(settings)
    flash("Mailbox saved and Fetchmail configuration regenerated.", "success")
    return redirect(url_for("index"))

@app.post("/accounts/<int:index>/delete")
@requires_auth
def delete_account(index):
    settings = load_settings()
    if index < 0 or index >= len(settings["accounts"]): return "Mailbox not found", 404
    settings["accounts"].pop(index); save_settings(settings)
    flash("Mailbox removed and configuration regenerated.", "success")
    return redirect(url_for("index"))
