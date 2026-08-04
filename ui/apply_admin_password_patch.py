from pathlib import Path

path = Path("/app/app_v2.py")
text = path.read_text(encoding="utf-8")

text = text.replace(
    "from connection_tests import test_exchange, test_provider\n",
    "from connection_tests import test_exchange, test_provider\nfrom auth_store import save_admin_password, verify_admin\n",
    1,
)

old_auth = '''        auth = request.authorization
        user = os.environ.get("UI_USERNAME", "admin")
        password = os.environ.get("UI_PASSWORD", "change-me-now")
        if not auth or not secrets.compare_digest(auth.username, user) or not secrets.compare_digest(auth.password, password):
            return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="MailGate"'})
'''
new_auth = '''        auth = request.authorization
        if not auth or not verify_admin(CONFIG_DIR, auth.username, auth.password):
            return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="MailGate"'})
'''
if old_auth not in text:
    raise SystemExit("Authentication block not found")
text = text.replace(old_auth, new_auth, 1)

marker = '<div class="card"><h2>Generated configuration</h2>'
password_card = '''<div class="card"><h2>Administration</h2>
<form method="post" action="{{ url_for('change_admin_password') }}">
<div class="grid">
<label>Current password<input required name="current_password" type="password" autocomplete="current-password"></label>
<label>New password<input required name="new_password" type="password" minlength="10" autocomplete="new-password"></label>
<label>Confirm new password<input required name="confirm_password" type="password" minlength="10" autocomplete="new-password"></label>
</div><p><button type="submit">Change admin password</button></p>
<p class="muted">The Portainer UI_PASSWORD value is used only until a password is saved here. The saved password is stored as a hash in the persistent config directory.</p>
</form></div>
'''
if marker not in text:
    raise SystemExit("HTML insertion marker not found")
text = text.replace(marker, password_card + marker, 1)

route = '''

@app.post("/admin/password")
@requires_auth
def change_admin_password():
    current = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirmation = request.form.get("confirm_password", "")
    username = os.environ.get("UI_USERNAME", "admin")

    if not verify_admin(CONFIG_DIR, username, current):
        flash("Current admin password is incorrect.", "error")
        return redirect(url_for("index"))
    if len(new_password) < 10:
        flash("The new password must contain at least 10 characters.", "error")
        return redirect(url_for("index"))
    if new_password != confirmation:
        flash("The new passwords do not match.", "error")
        return redirect(url_for("index"))
    if secrets.compare_digest(current, new_password):
        flash("The new password must be different from the current password.", "error")
        return redirect(url_for("index"))

    save_admin_password(CONFIG_DIR, new_password)
    return Response(
        "Admin password changed. Reload MailGate and sign in with the new password.",
        401,
        {"WWW-Authenticate": 'Basic realm="MailGate"'},
    )
'''
text = text.rstrip() + route + "\n"
path.write_text(text, encoding="utf-8")
