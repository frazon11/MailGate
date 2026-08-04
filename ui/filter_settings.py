import json
import os
import secrets
from pathlib import Path
from tempfile import NamedTemporaryFile

from flask import Blueprint, Response, flash, redirect, render_template_string, request, url_for

from auth_store import verify_admin

bp = Blueprint("filter_settings", __name__)
CONFIG_DIR = Path(os.environ.get("CONFIG_PATH", "/data/config"))
SETTINGS_FILE = CONFIG_DIR / "filter-settings.json"
RSPAMD_DIR = CONFIG_DIR / "rspamd"
OVERRIDE_DIR = RSPAMD_DIR / "override.d"
CUSTOM_COMMANDS = RSPAMD_DIR / "custom-commands.conf"
ACTIONS_FILE = OVERRIDE_DIR / "actions.conf"

DEFAULTS = {
    "spam_add_header": 6.0,
    "spam_reject": 15.0,
    "greylist": 4.0,
    "greylisting_enabled": False,
    "antivirus_enabled": True,
}

HTML = r"""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MailGate - Spam & Antivirus</title><style>
body{font-family:system-ui,sans-serif;background:#111827;color:#e5e7eb;margin:0}main{max-width:900px;margin:32px auto;padding:0 20px}
.card{background:#1f2937;border:1px solid #374151;border-radius:12px;padding:18px;margin:18px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
input{width:100%;box-sizing:border-box;background:#111827;color:#e5e7eb;border:1px solid #4b5563;border-radius:7px;padding:9px}
button,.button{display:inline-block;background:#2563eb;color:white;border:0;border-radius:7px;padding:9px 14px;text-decoration:none;cursor:pointer}.secondary{background:#4b5563}
.ok{background:#065f46;padding:10px;border-radius:7px}.error{background:#991b1b;padding:10px;border-radius:7px}.muted{color:#9ca3af}code{background:#111827;padding:2px 5px;border-radius:4px}
@media(max-width:700px){.grid{grid-template-columns:1fr}}
</style></head><body><main>
<h1>Spam & Antivirus</h1><p><a class="button secondary" href="/">Back to MailGate</a></p>
{% with messages=get_flashed_messages(with_categories=true) %}{% for category,message in messages %}<p class="{{ 'error' if category=='error' else 'ok' }}">{{ message }}</p>{% endfor %}{% endwith %}
<form method="post">
<div class="card"><h2>Rspamd actions</h2><div class="grid">
<label>Add spam headers at score<input name="spam_add_header" type="number" step="0.1" min="0" max="100" value="{{ s.spam_add_header }}"></label>
<label>Reject message at score<input name="spam_reject" type="number" step="0.1" min="0" max="100" value="{{ s.spam_reject }}"></label>
<label>Greylist at score<input name="greylist" type="number" step="0.1" min="0" max="100" value="{{ s.greylist }}"></label>
<label><input style="width:auto" name="greylisting_enabled" type="checkbox" {% if s.greylisting_enabled %}checked{% endif %}> Enable Rspamd greylisting</label>
</div><p class="muted">The reject threshold must be higher than the add-header threshold. Mail above the add-header score is tagged and forwarded; mail above the reject score is refused.</p></div>
<div class="card"><h2>Antivirus</h2><label><input style="width:auto" name="antivirus_enabled" type="checkbox" {% if s.antivirus_enabled %}checked{% endif %}> Scan messages with ClamAV</label>
<p class="muted">Disabling this turns off Rspamd's antivirus module. The ClamAV service remains installed so it can be re-enabled later.</p></div>
<p><button type="submit">Save filter settings</button></p></form>
<div class="card"><h2>Generated files</h2><p><code>{{ actions_file }}</code><br><code>{{ commands_file }}</code></p><p class="muted">Restart <code>mailgate-mailserver</code> after saving so Docker Mailserver reapplies the override configuration.</p></div>
</main></body></html>
"""


def _auth_ok():
    auth = request.authorization
    return bool(auth and verify_admin(CONFIG_DIR, auth.username, auth.password))


@bp.before_request
def require_auth():
    if not _auth_ok():
        return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="MailGate"'})


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = handle.name
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def load_settings():
    if not SETTINGS_FILE.exists():
        return DEFAULTS.copy()
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULTS.copy()
    result = DEFAULTS.copy()
    result.update({k: data[k] for k in result if k in data})
    return result


def save_settings(settings):
    _atomic_write(SETTINGS_FILE, json.dumps(settings, indent=2) + "\n")
    actions = (
        "actions {\n"
        f"  greylist = {settings['greylist']};\n"
        f"  add_header = {settings['spam_add_header']};\n"
        f"  reject = {settings['spam_reject']};\n"
        "}\n"
    )
    commands = ["# Managed by MailGate WebUI"]
    commands.append("enable-module antivirus" if settings["antivirus_enabled"] else "disable-module antivirus")
    commands.append("enable-module greylist" if settings["greylisting_enabled"] else "disable-module greylist")
    _atomic_write(ACTIONS_FILE, actions)
    _atomic_write(CUSTOM_COMMANDS, "\n".join(commands) + "\n")


@bp.route("/settings/filters", methods=["GET", "POST"])
def filters():
    settings = load_settings()
    if request.method == "POST":
        try:
            add_header = float(request.form.get("spam_add_header", "6"))
            reject = float(request.form.get("spam_reject", "15"))
            greylist = float(request.form.get("greylist", "4"))
            if not (0 <= greylist <= add_header < reject <= 100):
                raise ValueError("Required order: greylist ≤ add-header < reject, all between 0 and 100.")
            settings = {
                "spam_add_header": add_header,
                "spam_reject": reject,
                "greylist": greylist,
                "greylisting_enabled": request.form.get("greylisting_enabled") == "on",
                "antivirus_enabled": request.form.get("antivirus_enabled") == "on",
            }
            save_settings(settings)
            flash("Spam and antivirus settings saved. Restart mailgate-mailserver to apply them.", "success")
            return redirect(url_for("filter_settings.filters"))
        except (ValueError, OSError) as exc:
            flash(f"Could not save filter settings: {exc}", "error")
    return render_template_string(HTML, s=settings, actions_file=ACTIONS_FILE, commands_file=CUSTOM_COMMANDS)
