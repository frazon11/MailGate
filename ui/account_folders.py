import json

from flask import flash, redirect, render_template_string, request, url_for

import app_clean
from connection_tests import test_exchange, test_provider


def _normalise_folders(protocol, raw):
    if protocol != "imap":
        return ["INBOX"]
    folders = []
    for line in (raw or "INBOX").replace(",", "\n").splitlines():
        folder = line.strip()
        if folder and folder not in folders:
            folders.append(folder)
    return folders or ["INBOX"]


def migrate_accounts(settings):
    changed = False
    for account in settings.get("accounts", []):
        if "folders" not in account:
            account["folders"] = ["INBOX"]
            changed = True
        else:
            normalised = _normalise_folders(account.get("protocol", "imap"), "\n".join(account.get("folders") or []))
            if normalised != account["folders"]:
                account["folders"] = normalised
                changed = True
    if changed:
        app_clean.save_main(settings)
    return settings


def generate_fetchmail(accounts):
    lines = ["set no bouncemail", "set no spambounce", "set syslog", "defaults timeout 60", ""]
    for account in accounts:
        folders = _normalise_folders(account.get("protocol", "imap"), "\n".join(account.get("folders") or ["INBOX"]))
        for folder in folders:
            lines.extend([
                f"poll {json.dumps(account['host'])} protocol {account['protocol']}",
                f"  port {int(account['port'])}",
                f"  user {json.dumps(account['username'])}",
                f"  password {json.dumps(account['password'])}",
                "  ssl",
                f"  {'sslcertck' if account.get('verify_certificate', True) else 'no sslcertck'}",
            ])
            if account.get("protocol") == "imap":
                lines.append(f"  folder {json.dumps(folder)}")
            lines.extend([
                f"  {'keep' if account.get('keep', True) else 'no keep'}",
                f"  smtpname {json.dumps(account['recipient'])}",
                "  smtphost 127.0.0.1",
                "",
            ])
    return "\n".join(lines)


app_clean.generate_fetchmail = generate_fetchmail

ACCOUNTS_BODY = """
<div class="card"><h2>Target server</h2><form method="post"><div class="grid"><label>SMTP server<input name="delivery_host" value="{{ delivery.host }}" required></label><label>SMTP port<input name="delivery_port" type="number" value="{{ delivery.port }}" required></label><label>Fetch interval in seconds<input name="poll_interval" type="number" min="10" max="86400" value="{{ delivery.poll_interval }}"></label><label>Test sender<input name="test_sender" value="{{ delivery.sender }}"></label><label>Test recipient<input name="test_recipient" type="email" placeholder="user@example.com"></label></div><div class="actions"><button name="action" value="test-delivery" class="secondary">Test target and recipient</button><button name="action" value="save-delivery">Save target settings</button></div></form></div>
<div class="card"><h2>Provider accounts</h2>{% if configured %}<table><thead><tr><th>Provider</th><th>Login</th><th>Folders</th><th>Destination</th><th>TLS</th><th>Source handling</th><th></th></tr></thead><tbody>{% for a in configured %}<tr><td>{{ a.host }}:{{ a.port }}<br><span class="muted">{{ a.protocol|upper }}</span></td><td>{{ a.username }}</td><td>{% for folder in a.folders %}<code>{{ folder }}</code>{% if not loop.last %}<br>{% endif %}{% endfor %}</td><td>{{ a.recipient }}</td><td>{{ 'Verified' if a.verify_certificate else 'Verification disabled' }}</td><td>{{ 'Keep copy' if a.keep else 'Delete after accepted' }}</td><td><form method="post" action="{{ url_for('delete_account', index=loop.index0) }}"><button class="danger">Delete</button></form></td></tr>{% endfor %}</tbody></table>{% else %}<p class="warn">No provider accounts configured yet.</p>{% endif %}</div>
<div class="card"><h2>Add provider account</h2><form method="post"><div class="grid"><label>IMAP/POP server<input required name="host" placeholder="imap.example.com"></label><label>Port<input required name="port" type="number" value="993"></label><label>Protocol<select name="protocol"><option value="imap">IMAP</option><option value="pop3">POP3</option></select></label><label>Provider username<input required name="username" autocomplete="off"></label><label>Provider password<input required name="password" type="password" autocomplete="new-password"></label><label>Exchange recipient<input required name="recipient" type="email" placeholder="user@example.com"></label><label>IMAP folders, one per line<textarea name="folders" rows="4">INBOX</textarea><span class="muted">Examples: INBOX, Spam, Junk, Junk E-mail. POP3 ignores this field.</span></label><div><label><input type="checkbox" name="keep" checked>Keep messages at provider</label><label><input type="checkbox" name="verify_certificate" checked>Verify TLS certificate</label></div></div><div class="actions"><button name="action" value="test-provider" class="secondary">Test provider login</button><button name="action" value="save-account">Save account</button></div></form></div>
<div class="card"><h2>Generated Fetchmail configuration</h2><p><code>{{ fetchmail_file }}</code></p><pre>{{ generated }}</pre><p class="muted">Each selected IMAP folder generates a separate retrieval entry. Folder names must exactly match the provider's server-side IMAP mailbox name.</p></div>
"""


def accounts_view():
    settings = migrate_accounts(app_clean.load_settings())
    delivery = settings["delivery"]
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
                    flash(result, "success")
                else:
                    flash("Delivery settings saved. Restart mailgate-mailserver to apply relay and polling changes.", "success")
                app_clean.save_main(settings)
                return redirect(url_for("accounts"))

            protocol = request.form.get("protocol", "imap").lower()
            account = {
                "host": request.form.get("host", "").strip(),
                "port": int(request.form.get("port", "993")),
                "protocol": protocol,
                "username": request.form.get("username", "").strip(),
                "password": request.form.get("password", ""),
                "recipient": request.form.get("recipient", "").strip(),
                "keep": request.form.get("keep") == "on",
                "verify_certificate": request.form.get("verify_certificate") == "on",
                "folders": _normalise_folders(protocol, request.form.get("folders", "INBOX")),
            }
            if protocol not in {"imap", "pop3"} or not 1 <= account["port"] <= 65535 or not all(account[k] for k in ("host", "username", "password", "recipient")):
                raise ValueError("All account fields are required and must be valid.")
            if action == "test-provider":
                result = test_provider(account["host"], account["port"], protocol, account["username"], account["password"], account["verify_certificate"])
                settings.setdefault("checks", {})["provider"] = result
                app_clean.save_main(settings)
                flash(result + " Folder names are applied when the account is saved.", "success")
            elif action == "save-account":
                settings["accounts"].append(account)
                app_clean.save_main(settings)
                flash(f"Provider account saved with {len(account['folders'])} retrieval folder(s).", "success")
            return redirect(url_for("accounts"))
        except Exception as exc:
            flash(str(exc), "error")

    generated = generate_fetchmail(settings["accounts"])
    return render_template_string(app_clean.page("Accounts & Delivery", "accounts", ACCOUNTS_BODY), configured=settings["accounts"], delivery=delivery, generated=generated, fetchmail_file=app_clean.FETCHMAIL_FILE)


def install():
    app_clean.app.view_functions["accounts"] = app_clean.requires_auth(accounts_view)
    settings = migrate_accounts(app_clean.load_settings())
    app_clean.save_main(settings)
