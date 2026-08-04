import json
import os
import secrets
from functools import wraps
from pathlib import Path
from tempfile import NamedTemporaryFile

from flask import Flask, Response, flash, redirect, render_template_string, request, url_for

from auth_store import save_admin_password, verify_admin
from connection_tests import test_exchange, test_provider

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

CONFIG_DIR = Path(os.environ.get("CONFIG_PATH", "/data/config"))
SETTINGS_FILE = CONFIG_DIR / "mailgate.json"
FILTER_FILE = CONFIG_DIR / "filter-settings.json"
FETCHMAIL_FILE = CONFIG_DIR / "fetchmail.cf"
POSTFIX_FILE = CONFIG_DIR / "postfix-main.cf"
RSPAMD_DIR = CONFIG_DIR / "rspamd"
ACTIONS_FILE = RSPAMD_DIR / "override.d" / "actions.conf"
COMMANDS_FILE = RSPAMD_DIR / "custom-commands.conf"

VERSION = os.environ.get("MAILGATE_VERSION", "0.2.0")
BUILD = os.environ.get("MAILGATE_BUILD", "dev")

DEFAULT_FILTERS = {
    "spam_enabled": True,
    "spam_add_header": 6.0,
    "spam_reject": 15.0,
    "greylist": 4.0,
    "greylisting_enabled": False,
    "spam_subject": "[SPAM] ",
    "dns_reputation_sources": "Spamhaus ZEN\nSpamhaus DBL\nSURBL\nURIBL",
    "antivirus_enabled": True,
    "max_file_size_mb": 25,
    "max_scan_size_mb": 100,
    "scan_timeout_seconds": 20,
    "malware_action": "reject",
}

STYLE = """
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0f172a;color:#e5e7eb;font-family:system-ui,sans-serif}a{color:#93c5fd}header{background:#111827;border-bottom:1px solid #334155}header .wrap{max-width:1180px;margin:auto;padding:18px 22px;display:flex;align-items:center;justify-content:space-between;gap:20px}.brand{font-size:1.55rem;font-weight:750}.version{font-size:.78rem;color:#94a3b8;font-weight:500}nav{display:flex;flex-wrap:wrap;gap:8px}nav a{padding:8px 11px;border-radius:7px;text-decoration:none;color:#cbd5e1}nav a.active,nav a:hover{background:#2563eb;color:white}main{max-width:1180px;margin:24px auto;padding:0 22px}.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.metric{background:#111827;border-radius:9px;padding:14px}.metric strong{display:block;font-size:1.3rem;margin-top:5px}.muted{color:#94a3b8}.ok,.error,.warn{padding:11px 13px;border-radius:8px;white-space:pre-wrap}.ok{background:#065f46}.error{background:#991b1b}.warn{background:#92400e}label{display:block}input,select,textarea{width:100%;margin-top:5px;background:#0f172a;color:#e5e7eb;border:1px solid #475569;border-radius:7px;padding:9px}input[type=checkbox]{width:auto;margin-right:7px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}button,.button{display:inline-block;background:#2563eb;color:#fff;border:0;border-radius:7px;padding:9px 14px;text-decoration:none;cursor:pointer}.secondary{background:#475569}.danger{background:#b91c1c}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #334155;vertical-align:top}code,pre{background:#0f172a;border-radius:6px}code{padding:2px 5px}pre{padding:12px;white-space:pre-wrap;overflow:auto}.badge{display:inline-block;padding:3px 8px;border-radius:999px;background:#334155;font-size:.8rem}.good{background:#065f46}.bad{background:#991b1b}@media(max-width:850px){.grid,.grid3{grid-template-columns:1fr}header .wrap{align-items:flex-start;flex-direction:column}table{display:block;overflow:auto}}
"""


def nav(active):
    items = [("dashboard", "Dashboard", "/"), ("accounts", "Accounts & Delivery", "/accounts"), ("spam", "Spam Protection", "/spam"), ("antivirus", "Antivirus", "/antivirus"), ("security", "Security / Profile", "/security")]
    return "".join(f'<a class="{"active" if key == active else ""}" href="{href}">{label}</a>' for key, label, href in items)


def page(title, active, body):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MailGate - {title}</title><style>{STYLE}</style></head><body><header><div class="wrap"><div class="brand">MailGate <span class="version">v{VERSION} · build {BUILD}</span></div><nav>{nav(active)}</nav></div></header><main><h1>{title}</h1>{{% with messages=get_flashed_messages(with_categories=true) %}}{{% for category,message in messages %}}<p class="{{{{ 'error' if category=='error' else ('warn' if category=='warning' else 'ok') }}}}">{{{{ message }}}}</p>{{% endfor %}}{{% endwith %}}{body}</main></body></html>"""


def requires_auth(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth or not verify_admin(CONFIG_DIR, auth.username, auth.password):
            return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="MailGate"'})
        return func(*args, **kwargs)
    return wrapped


def atomic_write(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = handle.name
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def load_json(path, default):
    if not path.exists():
        return default.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default.copy()
    except (OSError, json.JSONDecodeError):
        return default.copy()


def default_settings():
    return {
        "accounts": [],
        "delivery": {
            "host": os.environ.get("EXCHANGE_HOST", ""),
            "port": int(os.environ.get("EXCHANGE_PORT", "25")),
            "sender": os.environ.get("TEST_SENDER", "mailgate-test@localhost"),
            "poll_interval": int(os.environ.get("FETCHMAIL_POLL_INTERVAL", "60")),
        },
        "checks": {},
    }


def load_settings():
    data = load_json(SETTINGS_FILE, default_settings())
    base = default_settings()
    base.update(data)
    base["delivery"].update(data.get("delivery", {}))
    for account in base.get("accounts", []):
        account.setdefault("verify_certificate", True)
        account.setdefault("keep", True)
    return base


def save_main(settings):
    atomic_write(SETTINGS_FILE, json.dumps(settings, indent=2) + "\n")
    atomic_write(FETCHMAIL_FILE, generate_fetchmail(settings.get("accounts", [])))
    delivery = settings["delivery"]
    atomic_write(POSTFIX_FILE, f"relayhost = [{delivery['host']}]:{int(delivery['port'])}\n")


def load_filters():
    data = load_json(FILTER_FILE, DEFAULT_FILTERS)
    result = DEFAULT_FILTERS.copy()
    result.update({key: data[key] for key in result if key in data})
    return result


def save_filters(filters):
    atomic_write(FILTER_FILE, json.dumps(filters, indent=2) + "\n")
    actions = "actions {\n" + f"  greylist = {filters['greylist']};\n  add_header = {filters['spam_add_header']};\n  reject = {filters['spam_reject']};\n" + "}\n"
    commands = ["# Managed by MailGate WebUI"]
    commands.append("enable-module spamassassin" if filters["spam_enabled"] else "disable-module spamassassin")
    commands.append("enable-module greylist" if filters["greylisting_enabled"] else "disable-module greylist")
    commands.append("enable-module antivirus" if filters["antivirus_enabled"] else "disable-module antivirus")
    atomic_write(ACTIONS_FILE, actions)
    atomic_write(COMMANDS_FILE, "\n".join(commands) + "\n")


def generate_fetchmail(accounts):
    lines = ["set no bouncemail", "set no spambounce", "set syslog", "defaults timeout 60", ""]
    for account in accounts:
        lines.extend([
            f"poll {json.dumps(account['host'])} protocol {account['protocol']}",
            f"  port {int(account['port'])}",
            f"  user {json.dumps(account['username'])}",
            f"  password {json.dumps(account['password'])}",
            "  ssl",
            f"  {'sslcertck' if account.get('verify_certificate', True) else 'no sslcertck'}",
            f"  {'keep' if account.get('keep', True) else 'no keep'}",
            f"  smtpname {json.dumps(account['recipient'])}",
            "  smtphost 127.0.0.1",
            "",
        ])
    return "\n".join(lines)


@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION, "build": BUILD}


@app.get("/")
@requires_auth
def dashboard():
    settings = load_settings(); filters = load_filters(); delivery = settings["delivery"]
    body = """
<div class="grid3">
<div class="metric"><span class="muted">Provider accounts</span><strong>{{ account_count }}</strong></div>
<div class="metric"><span class="muted">Target server</span><strong>{{ delivery.host }}:{{ delivery.port }}</strong></div>
<div class="metric"><span class="muted">Fetch interval</span><strong>{{ delivery.poll_interval }} sec</strong></div>
<div class="metric"><span class="muted">Spam protection</span><strong>{{ 'Enabled' if filters.spam_enabled else 'Disabled' }}</strong></div>
<div class="metric"><span class="muted">Antivirus</span><strong>{{ 'Enabled' if filters.antivirus_enabled else 'Disabled' }}</strong></div>
<div class="metric"><span class="muted">Configuration</span><strong>{{ 'Ready' if account_count and delivery.host else 'Incomplete' }}</strong></div>
</div>
<div class="card"><h2>Operational status</h2><p>This dashboard reports only configuration that MailGate can verify directly. Runtime Rspamd and ClamAV versions will remain marked unavailable until a restricted status agent is added.</p><div class="grid"><div><strong>Last provider test</strong><p class="muted">{{ checks.get('provider','Not tested yet') }}</p></div><div><strong>Last delivery test</strong><p class="muted">{{ checks.get('delivery','Not tested yet') }}</p></div></div></div>
"""
    return render_template_string(page("Dashboard", "dashboard", body), account_count=len(settings["accounts"]), delivery=delivery, filters=filters, checks=settings.get("checks", {}))


@app.route("/accounts", methods=["GET", "POST"])
@requires_auth
def accounts():
    settings = load_settings(); delivery = settings["delivery"]
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action in {"save-delivery", "test-delivery"}:
                delivery["host"] = request.form.get("delivery_host", "").strip()
                delivery["port"] = int(request.form.get("delivery_port", "25"))
                delivery["sender"] = request.form.get("test_sender", "mailgate-test@localhost").strip()
                delivery["poll_interval"] = int(request.form.get("poll_interval", "60"))
                if not delivery["host"] or not 1 <= delivery["port"] <= 65535 or not 10 <= delivery["poll_interval"] <= 86400:
                    raise ValueError("Invalid delivery server, port, or polling interval.")
                if action == "test-delivery":
                    recipient = request.form.get("test_recipient", "").strip()
                    result = test_exchange(delivery["host"], delivery["port"], recipient, delivery["sender"])
                    settings.setdefault("checks", {})["delivery"] = result
                    save_main(settings)
                    flash(result, "success")
                else:
                    save_main(settings)
                    flash("Delivery settings saved. Restart mailgate-mailserver to apply relay and polling changes.", "success")
                return redirect(url_for("accounts"))

            account = {
                "host": request.form.get("host", "").strip(),
                "port": int(request.form.get("port", "993")),
                "protocol": request.form.get("protocol", "imap").lower(),
                "username": request.form.get("username", "").strip(),
                "password": request.form.get("password", ""),
                "recipient": request.form.get("recipient", "").strip(),
                "keep": request.form.get("keep") == "on",
                "verify_certificate": request.form.get("verify_certificate") == "on",
            }
            if account["protocol"] not in {"imap", "pop3"} or not 1 <= account["port"] <= 65535 or not all(account[k] for k in ("host", "username", "password", "recipient")):
                raise ValueError("All account fields are required and must be valid.")
            if action == "test-provider":
                result = test_provider(account["host"], account["port"], account["protocol"], account["username"], account["password"], account["verify_certificate"])
                settings.setdefault("checks", {})["provider"] = result
                save_main(settings)
                flash(result, "success")
            elif action == "save-account":
                settings["accounts"].append(account); save_main(settings)
                flash("Provider account saved and Fetchmail configuration regenerated.", "success")
            return redirect(url_for("accounts"))
        except Exception as exc:
            flash(str(exc), "error")

    body = """
<div class="card"><h2>Target server</h2><form method="post"><div class="grid"><label>SMTP server<input name="delivery_host" value="{{ delivery.host }}" required></label><label>SMTP port<input name="delivery_port" type="number" value="{{ delivery.port }}" required></label><label>Fetch interval in seconds<input name="poll_interval" type="number" min="10" max="86400" value="{{ delivery.poll_interval }}"></label><label>Test sender<input name="test_sender" value="{{ delivery.sender }}"></label><label>Test recipient<input name="test_recipient" type="email" placeholder="user@example.com"></label></div><div class="actions"><button name="action" value="test-delivery" class="secondary">Test target and recipient</button><button name="action" value="save-delivery">Save target settings</button></div><p class="muted">Saving writes a Postfix relay override. Restart mailgate-mailserver after changing target or polling settings.</p></form></div>
<div class="card"><h2>Provider accounts</h2>{% if configured %}<table><thead><tr><th>Provider</th><th>Login</th><th>Destination</th><th>TLS</th><th>Source handling</th><th></th></tr></thead><tbody>{% for a in configured %}<tr><td>{{ a.host }}:{{ a.port }} / {{ a.protocol|upper }}</td><td>{{ a.username }}</td><td>{{ a.recipient }}</td><td>{{ 'Verified' if a.verify_certificate else 'Unverified' }}</td><td>{{ 'Keep copy' if a.keep else 'Delete after delivery' }}</td><td><form method="post" action="{{ url_for('delete_account', index=loop.index0) }}"><button class="danger">Delete</button></form></td></tr>{% endfor %}</tbody></table>{% else %}<p class="warn">No provider accounts configured.</p>{% endif %}</div>
<div class="card"><h2>Add provider account</h2><form method="post"><div class="grid"><label>IMAP/POP server<input name="host" required></label><label>Port<input name="port" type="number" value="993" required></label><label>Protocol<select name="protocol"><option value="imap">IMAP</option><option value="pop3">POP3</option></select></label><label>Provider username<input name="username" required autocomplete="off"></label><label>Provider password<input name="password" type="password" required autocomplete="new-password"></label><label>Target mailbox<input name="recipient" type="email" required></label><label><input type="checkbox" name="keep" checked>Keep messages at provider</label><label><input type="checkbox" name="verify_certificate" checked>Verify provider TLS certificate</label></div><div class="actions"><button name="action" value="test-provider" class="secondary">Test provider login</button><button name="action" value="save-account">Save account</button></div></form></div>
"""
    return render_template_string(page("Accounts & Delivery", "accounts", body), delivery=delivery, configured=settings["accounts"])


@app.post("/accounts/<int:index>/delete")
@requires_auth
def delete_account(index):
    settings = load_settings()
    if not 0 <= index < len(settings["accounts"]):
        return "Account not found", 404
    settings["accounts"].pop(index); save_main(settings); flash("Provider account removed.", "success")
    return redirect(url_for("accounts"))


@app.route("/spam", methods=["GET", "POST"])
@requires_auth
def spam():
    filters = load_filters()
    if request.method == "POST":
        try:
            filters.update({
                "spam_enabled": request.form.get("spam_enabled") == "on",
                "spam_add_header": float(request.form.get("spam_add_header", "6")),
                "spam_reject": float(request.form.get("spam_reject", "15")),
                "greylist": float(request.form.get("greylist", "4")),
                "greylisting_enabled": request.form.get("greylisting_enabled") == "on",
                "spam_subject": request.form.get("spam_subject", "[SPAM] "),
                "dns_reputation_sources": request.form.get("dns_reputation_sources", "").strip(),
            })
            if not 0 <= filters["greylist"] <= filters["spam_add_header"] < filters["spam_reject"] <= 100:
                raise ValueError("Required order: greylist ≤ add-header < reject.")
            save_filters(filters); flash("Spam settings saved. Restart mailgate-mailserver to apply them.", "success")
            return redirect(url_for("spam"))
        except Exception as exc:
            flash(str(exc), "error")
    body = """
<div class="card"><form method="post"><div class="grid"><label><input type="checkbox" name="spam_enabled" {% if f.spam_enabled %}checked{% endif %}>Enable spam filtering</label><label>Spam subject prefix<input name="spam_subject" value="{{ f.spam_subject }}"></label><label>Add headers at score<input type="number" step="0.1" name="spam_add_header" value="{{ f.spam_add_header }}"></label><label>Reject at score<input type="number" step="0.1" name="spam_reject" value="{{ f.spam_reject }}"></label><label>Greylist at score<input type="number" step="0.1" name="greylist" value="{{ f.greylist }}"></label><label><input type="checkbox" name="greylisting_enabled" {% if f.greylisting_enabled %}checked{% endif %}>Enable local greylisting</label></div><label style="margin-top:14px">DNS reputation sources / RBL overview<textarea name="dns_reputation_sources" rows="6">{{ f.dns_reputation_sources }}</textarea></label><p class="muted">Greylisting is local temporary deferral. DNS reputation sources are public block/reputation lists; the list above is currently informational and is not automatically pushed into Rspamd until provider-specific configuration validation is added.</p><button>Save spam settings</button></form></div>
<div class="card"><h2>Generated Rspamd settings</h2><p><code>{{ actions_file }}</code><br><code>{{ commands_file }}</code></p><pre>{{ generated }}</pre></div>
"""
    generated = ACTIONS_FILE.read_text(encoding="utf-8") if ACTIONS_FILE.exists() else "No generated Rspamd override yet."
    return render_template_string(page("Spam Protection", "spam", body), f=filters, actions_file=ACTIONS_FILE, commands_file=COMMANDS_FILE, generated=generated)


@app.route("/antivirus", methods=["GET", "POST"])
@requires_auth
def antivirus():
    filters = load_filters()
    if request.method == "POST":
        try:
            filters.update({
                "antivirus_enabled": request.form.get("antivirus_enabled") == "on",
                "max_file_size_mb": int(request.form.get("max_file_size_mb", "25")),
                "max_scan_size_mb": int(request.form.get("max_scan_size_mb", "100")),
                "scan_timeout_seconds": int(request.form.get("scan_timeout_seconds", "20")),
                "malware_action": request.form.get("malware_action", "reject"),
            })
            if filters["malware_action"] not in {"reject", "tag", "quarantine"} or min(filters["max_file_size_mb"], filters["max_scan_size_mb"], filters["scan_timeout_seconds"]) <= 0:
                raise ValueError("Invalid antivirus settings.")
            save_filters(filters); flash("Antivirus settings saved. Restart mailgate-mailserver to apply module changes.", "success")
            return redirect(url_for("antivirus"))
        except Exception as exc:
            flash(str(exc), "error")
    body = """
<div class="card"><form method="post"><div class="grid"><label><input type="checkbox" name="antivirus_enabled" {% if f.antivirus_enabled %}checked{% endif %}>Enable ClamAV scanning</label><label>Malware action<select name="malware_action"><option value="reject" {% if f.malware_action=='reject' %}selected{% endif %}>Reject</option><option value="tag" {% if f.malware_action=='tag' %}selected{% endif %}>Tag and deliver</option><option value="quarantine" {% if f.malware_action=='quarantine' %}selected{% endif %}>Quarantine</option></select></label><label>Maximum file size (MB)<input type="number" name="max_file_size_mb" value="{{ f.max_file_size_mb }}"></label><label>Maximum scan size (MB)<input type="number" name="max_scan_size_mb" value="{{ f.max_scan_size_mb }}"></label><label>Scan timeout (seconds)<input type="number" name="scan_timeout_seconds" value="{{ f.scan_timeout_seconds }}"></label></div><button>Save antivirus settings</button></form></div>
<div class="card"><h2>ClamAV runtime details</h2><table><tr><th>Engine version</th><td><span class="badge">Unavailable</span></td></tr><tr><th>Signature database version</th><td><span class="badge">Unavailable</span></td></tr><tr><th>Loaded signatures</th><td><span class="badge">Unavailable</span></td></tr><tr><th>Last signature update</th><td><span class="badge">Unavailable</span></td></tr></table><p class="muted">These values require a restricted internal status agent. MailGate does not guess them and does not mount the Docker socket.</p></div>
"""
    return render_template_string(page("Antivirus", "antivirus", body), f=filters)


@app.route("/security", methods=["GET", "POST"])
@requires_auth
def security():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        auth = request.authorization
        if not auth or not verify_admin(CONFIG_DIR, auth.username, current):
            flash("Current password is incorrect.", "error")
        elif len(new) < 10:
            flash("New password must contain at least 10 characters.", "error")
        elif new != confirm:
            flash("New passwords do not match.", "error")
        else:
            save_admin_password(CONFIG_DIR, new); flash("Admin password changed. Your browser may request the new credentials immediately.", "success")
            return Response("Password changed. Sign in again.", 401, {"WWW-Authenticate": 'Basic realm="MailGate"'})
    body = """
<div class="card"><h2>Administrator profile</h2><p>Username: <code>{{ username }}</code></p><form method="post"><div class="grid"><label>Current password<input type="password" name="current_password" required></label><label>New password<input type="password" name="new_password" minlength="10" required></label><label>Confirm new password<input type="password" name="confirm_password" minlength="10" required></label></div><button>Change admin password</button></form><p class="muted">The Portainer UI_PASSWORD value is used only as the bootstrap password until a password is saved here.</p></div>
"""
    return render_template_string(page("Security / Profile", "security", body), username=os.environ.get("UI_USERNAME", "admin"))
