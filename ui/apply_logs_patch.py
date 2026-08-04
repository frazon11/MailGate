from pathlib import Path

path = Path('/app/app_v2.py')
text = path.read_text(encoding='utf-8')

text = text.replace(
    'FETCHMAIL_FILE = CONFIG_DIR / "fetchmail.cf"\n',
    'FETCHMAIL_FILE = CONFIG_DIR / "fetchmail.cf"\nLOG_DIR = Path(os.environ.get("MAIL_LOG_PATH", "/data/mail-logs"))\n',
    1,
)

text = text.replace(
    '<div class="card"><h2>Backend</h2>',
    '<p class="actions"><a href="{{ url_for(\'logs\') }}" style="color:#fff;background:#4b5563;padding:9px 14px;border-radius:7px;text-decoration:none">Logs / Status</a></p><div class="card"><h2>Backend</h2>',
    1,
)

append = r'''

LOG_HTML = r"""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15"><title>MailGate Logs</title><style>
body{font-family:system-ui,sans-serif;background:#111827;color:#e5e7eb;margin:0}main{max-width:1400px;margin:28px auto;padding:0 20px}
a{color:#93c5fd}.card{background:#1f2937;border:1px solid #374151;border-radius:12px;padding:18px;margin:18px 0}
pre{white-space:pre-wrap;word-break:break-word;background:#030712;padding:14px;border-radius:8px;max-height:70vh;overflow:auto}.muted{color:#9ca3af}
</style></head><body><main><h1>MailGate Logs / Status</h1><p><a href="{{ url_for('index') }}">Back to configuration</a> · refreshes every 15 seconds</p>
<div class="card"><strong>Log directory:</strong> <code>{{ log_dir }}</code><br><strong>Files found:</strong> {{ file_count }}<br><span class="muted">Showing the newest {{ line_limit }} lines across available mail log files.</span></div>
<div class="card"><pre>{{ log_text }}</pre></div></main></body></html>
"""


def read_recent_logs(line_limit=500):
    if not LOG_DIR.exists():
        return "No persistent mail log directory is available yet.", 0
    candidates = []
    for item in LOG_DIR.rglob('*'):
        if item.is_file() and item.stat().st_size <= 100 * 1024 * 1024:
            candidates.append(item)
    candidates.sort(key=lambda p: p.stat().st_mtime)
    collected = []
    for item in candidates[-10:]:
        try:
            lines = item.read_text(encoding='utf-8', errors='replace').splitlines()
            collected.append(f"\n===== {item.relative_to(LOG_DIR)} =====")
            collected.extend(lines[-line_limit:])
        except OSError as exc:
            collected.append(f"\n===== {item.name}: cannot read: {exc} =====")
    if not collected:
        return "No mail log files have been written yet. Check the mailserver container log in Portainer during initial startup.", 0
    return "\n".join(collected[-line_limit:]), len(candidates)


@app.get('/logs')
@requires_auth
def logs():
    log_text, file_count = read_recent_logs()
    return render_template_string(LOG_HTML, log_text=log_text, log_dir=str(LOG_DIR), file_count=file_count, line_limit=500)
'''

text += append
path.write_text(text, encoding='utf-8')
