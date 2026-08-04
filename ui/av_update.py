import json
import os
from pathlib import Path

CONTROL_DIR = Path(os.environ.get("AV_UPDATE_CONTROL_PATH", "/data/config/av-update"))
REQUEST_FILE = CONTROL_DIR / "av-update.request"
STATUS_FILE = CONTROL_DIR / "av-update-status.json"
LOG_FILE = CONTROL_DIR / "av-update.log"


def request_update():
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    if STATUS_FILE.exists():
        try:
            current = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            if current.get("state") == "running":
                return False, "An antivirus signature update is already running."
        except (OSError, json.JSONDecodeError):
            pass
    REQUEST_FILE.write_text("update\n", encoding="utf-8")
    os.chmod(REQUEST_FILE, 0o664)
    return True, "Antivirus signature update requested. Refresh this page in a few seconds to see the result."


def read_update_status():
    default = {
        "state": "idle",
        "started_at": "",
        "finished_at": "",
        "exit_code": 0,
        "message": "No manual update has been requested yet.",
        "log": "",
    }
    try:
        if STATUS_FILE.exists():
            data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                default.update(data)
    except (OSError, json.JSONDecodeError):
        default["state"] = "error"
        default["message"] = "Could not read the antivirus update status file."
    try:
        if LOG_FILE.exists():
            default["log"] = LOG_FILE.read_text(encoding="utf-8", errors="replace")[-12000:]
    except OSError:
        pass
    return default
