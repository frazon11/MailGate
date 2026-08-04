import json
import os
from pathlib import Path

from flask import flash, redirect, request, url_for

import account_folders
import app_clean

CONTROL_DIR = Path(os.environ.get("FETCH_NOW_CONTROL_PATH", "/data/config/fetch-now"))
REQUEST_FILE = CONTROL_DIR / "fetch-now.request"
STATUS_FILE = CONTROL_DIR / "fetch-now-status.json"

FETCH_NOW_CARD = """
<div class="card"><h2>Manual retrieval</h2><form method="post" action="/accounts/fetch-now"><div class="actions"><button>Fetch mail now</button></div><p class="muted">Wakes all running Fetchmail workers and starts an immediate provider poll without restarting the mailserver.</p></form></div>
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
        previous = _last_status()
        if previous.get("state") == "success":
            previous_message = previous.get("message", "")
        else:
            previous_message = ""
        REQUEST_FILE.write_text("fetch now\n", encoding="utf-8")
        message = "Immediate mail retrieval requested."
        if previous_message:
            message += f" Previous result: {previous_message}"
        flash(message, "success")
        return redirect(url_for("accounts"))
