import os

from flask import Response, flash, redirect, render_template_string, request, url_for

import app_clean
from activity_log import bp as activity_log_blueprint
from auth_store import verify_admin
from av_status import read_clamav_status

app = app_clean.app


def _nav_with_activity(active):
    items = [
        ("dashboard", "Dashboard", "/"),
        ("accounts", "Accounts & Delivery", "/accounts"),
        ("spam", "Spam Protection", "/spam"),
        ("antivirus", "Antivirus", "/antivirus"),
        ("activity", "Activity Log", "/activity"),
        ("security", "Security / Profile", "/security"),
    ]
    return "".join(
        f'<a class="{"active" if key == active else ""}" href="{href}">{label}</a>'
        for key, label, href in items
    )


app_clean.nav = _nav_with_activity
app.register_blueprint(activity_log_blueprint)

AV_BODY = """
<div class="card"><form method="post"><div class="grid"><label><input type="checkbox" name="antivirus_enabled" {% if f.antivirus_enabled %}checked{% endif %}>Enable ClamAV scanning</label><label>Malware action<select name="malware_action"><option value="reject" {% if f.malware_action=='reject' %}selected{% endif %}>Reject</option><option value="tag" {% if f.malware_action=='tag' %}selected{% endif %}>Tag and deliver</option><option value="quarantine" {% if f.malware_action=='quarantine' %}selected{% endif %}>Quarantine</option></select></label><label>Maximum file size (MB)<input type="number" name="max_file_size_mb" value="{{ f.max_file_size_mb }}"></label><label>Maximum scan size (MB)<input type="number" name="max_scan_size_mb" value="{{ f.max_scan_size_mb }}"></label><label>Scan timeout (seconds)<input type="number" name="scan_timeout_seconds" value="{{ f.scan_timeout_seconds }}"></label></div><button>Save antivirus settings</button></form></div>
<div class="grid3">
<div class="metric"><span class="muted">Scanner configuration</span><strong>{{ 'Enabled' if f.antivirus_enabled else 'Disabled' }}</strong></div>
<div class="metric"><span class="muted">Known signatures</span><strong>{{ status.total_signatures if status.total_signatures else 'Unavailable' }}</strong></div>
<div class="metric"><span class="muted">Database freshness</span><strong>{{ status.freshness }}</strong></div>
</div>
<div class="card"><h2>ClamAV signature databases</h2>
{% if not status.state_available %}<p class="warn">The ClamAV state volume is not accessible at <code>{{ status.state_path }}</code>.</p>
{% elif not status.databases %}<p class="warn">No <code>.cvd</code>, <code>.cld</code> or <code>.cud</code> signature databases were found yet. ClamAV may still be performing its first update.</p>
{% else %}<table><thead><tr><th>Database</th><th>Version</th><th>Signatures</th><th>Built</th><th>File updated</th><th>Age</th><th>Size</th></tr></thead><tbody>{% for d in status.databases %}<tr><td><code>{{ d.name }}</code><br><span class="muted">Builder: {{ d.builder }} · F-level: {{ d.functionality_level }}</span></td><td>{{ d.version }}</td><td>{{ d.signatures if d.signatures is not none else 'Unknown' }}</td><td>{{ d.built }}</td><td>{{ d.modified }}</td><td>{{ d.age_hours }} h</td><td>{{ d.size_mb }} MB</td></tr>{% endfor %}</tbody></table>{% endif %}
</div>
<div class="card"><h2>Scanner runtime</h2><table><tr><th>ClamAV engine version</th><td><span class="badge">Not exposed yet</span></td></tr><tr><th>Clamd process status</th><td><span class="badge">Not exposed yet</span></td></tr><tr><th>Loaded database version</th><td><span class="badge">Not exposed yet</span></td></tr><tr><th>Persistent signature state</th><td><code>{{ status.state_path }}</code></td></tr></table><p class="muted">Signature versions and counts above are read directly from the persistent ClamAV database files. Live daemon values require a restricted internal clamd status channel; MailGate does not mount the Docker socket.</p></div>
"""


def _authorized():
    auth = request.authorization
    return bool(auth and verify_admin(app_clean.CONFIG_DIR, auth.username, auth.password))


@app.before_request
def structured_antivirus_page():
    if request.path != "/antivirus":
        return None
    if not _authorized():
        return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="MailGate"'})

    filters = app_clean.load_filters()
    if request.method == "POST":
        try:
            filters.update({
                "antivirus_enabled": request.form.get("antivirus_enabled") == "on",
                "max_file_size_mb": int(request.form.get("max_file_size_mb", "25")),
                "max_scan_size_mb": int(request.form.get("max_scan_size_mb", "100")),
                "scan_timeout_seconds": int(request.form.get("scan_timeout_seconds", "20")),
                "malware_action": request.form.get("malware_action", "reject"),
            })
            if filters["malware_action"] not in {"reject", "tag", "quarantine"}:
                raise ValueError("Invalid malware action.")
            if min(filters["max_file_size_mb"], filters["max_scan_size_mb"], filters["scan_timeout_seconds"]) <= 0:
                raise ValueError("Size and timeout values must be greater than zero.")
            app_clean.save_filters(filters)
            flash("Antivirus settings saved. Restart mailgate-mailserver to apply module changes.", "success")
            return redirect(url_for("antivirus"))
        except (ValueError, OSError) as exc:
            flash(str(exc), "error")

    return render_template_string(
        app_clean.page("Antivirus", "antivirus", AV_BODY),
        f=filters,
        status=read_clamav_status(),
    )
