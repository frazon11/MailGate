from pathlib import Path

path = Path('/app/app_v2.py')
text = path.read_text(encoding='utf-8')

text = text.replace(
    'import secrets\n',
    'import secrets\nimport subprocess\n',
    1,
)

button = '''<div class="card"><h2>Mail retrieval</h2>
<form method="post" action="{{ url_for('download_now') }}">
<p class="actions"><button type="submit">Download emails now</button></p>
<p class="muted">Runs one immediate Fetchmail cycle inside the mailserver container. The normal polling schedule continues unchanged.</p>
</form></div>\n'''

anchor = '<div class="card"><h2>Backend</h2>'
if button not in text:
    text = text.replace(anchor, button + anchor, 1)

route = '''\n\n@app.post("/download-now")
@requires_auth
def download_now():
    container = os.environ.get("MAILSERVER_CONTAINER", "mailgate-mailserver").strip()
    if not container:
        flash("Manual download failed: mailserver container name is not configured.", "error")
        return redirect(url_for("index"))

    try:
        result = subprocess.run(
            ["docker", "exec", container, "setup", "debug", "fetchmail"],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except FileNotFoundError:
        flash("Manual download failed: Docker CLI is unavailable in the UI container.", "error")
        return redirect(url_for("index"))
    except subprocess.TimeoutExpired:
        flash("Manual download timed out after 180 seconds. Check Logs / Status.", "error")
        return redirect(url_for("index"))
    except OSError as exc:
        flash(f"Manual download failed: {exc}", "error")
        return redirect(url_for("index"))

    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    tail = output[-1800:] if output else "No command output was returned."

    # Fetchmail status 1 means a successful run with no mail available.
    if result.returncode in (0, 1):
        flash(f"Manual mail download completed (status {result.returncode}).\n{tail}", "success")
    else:
        flash(f"Manual mail download failed (status {result.returncode}).\n{tail}", "error")
    return redirect(url_for("index"))
'''

if '@app.post("/download-now")' not in text:
    text = text.rstrip() + route + '\n'

path.write_text(text, encoding='utf-8')
