import json
import os
from pathlib import Path

from flask import flash, redirect, url_for

import account_folders
import app_clean

CONTROL_DIR = Path(os.environ.get("FETCH_NOW_CONTROL_PATH", "/data/config/fetch-now"))
REQUEST_FILE = CONTROL_DIR / "fetch-now.request"
STATUS_FILE = CONTROL_DIR / "fetcher-status.json"

FETCH_NOW_CARD = """
<div class="card"><h2>Mailbox retrieval</h2><form method="post" action="/accounts/fetch-now"><div class="actions"><button>Fetch mail now</button><a class="button secondary" href="/mail-flow">Open Mail Flow</a></div><p class="muted">Requests an immediate real mailbox poll by the dedicated MailGate fetcher. The complete result is written to Mail Flow.</p></form></div>
"""


def _last_status():
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def install():
    if FETCH_NOW_CARD not in account_folders.ACCOUNTS_BODY:
        marker = '<div class="card"><h2>Provider accounts</h2>'
        account_folders.ACCOUNTS_BODY = account_folders.ACCOUNTS_BODY.replace(marker, FETCH_NOW_CARD + marker, 1)

    @app_clean.app.post("/accounts/fetch-now")
    @app_clean.requires_auth
    def fetch_now():
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        REQUEST_FILE.write_text("fetch now\n", encoding="utf-8")
        previous = _last_status()
        suffix = f" Last completed result: {previous.get('message')}" if previous.get("message") else ""
        flash("Immediate mailbox poll requested." + suffix, "success")
        return redirect(url_for("accounts"))
