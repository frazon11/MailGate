import json
import os
import secrets
from pathlib import Path
from tempfile import NamedTemporaryFile

from werkzeug.security import check_password_hash, generate_password_hash


def _credentials_file(config_dir: Path) -> Path:
    return config_dir / "admin-credentials.json"


def _read_hash(config_dir: Path) -> str | None:
    path = _credentials_file(config_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("password_hash")
        return value if isinstance(value, str) and value else None
    except (OSError, json.JSONDecodeError):
        return None


def verify_admin(config_dir: Path, username: str, password: str) -> bool:
    expected_user = os.environ.get("UI_USERNAME", "admin")
    if not secrets.compare_digest(username or "", expected_user):
        return False

    stored_hash = _read_hash(config_dir)
    if stored_hash:
        return check_password_hash(stored_hash, password or "")

    bootstrap_password = os.environ.get("UI_PASSWORD", "change-me-now")
    return secrets.compare_digest(password or "", bootstrap_password)


def save_admin_password(config_dir: Path, password: str) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    target = _credentials_file(config_dir)
    payload = json.dumps({"password_hash": generate_password_hash(password)}, indent=2) + "\n"
    with NamedTemporaryFile("w", encoding="utf-8", dir=config_dir, delete=False) as handle:
        handle.write(payload)
        temporary = handle.name
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
