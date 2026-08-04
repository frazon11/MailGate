import os
from datetime import datetime, timezone
from pathlib import Path


def _format_time(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _parse_cvd_header(path):
    info = {
        "name": path.name,
        "path": str(path),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 2),
        "modified": _format_time(path.stat().st_mtime),
        "age_hours": round((datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600, 1),
        "version": "Unknown",
        "signatures": None,
        "built": "Unknown",
        "functionality_level": "Unknown",
        "builder": "Unknown",
    }
    try:
        header = path.open("rb").read(512).split(b"\0", 1)[0].decode("ascii", errors="replace")
        parts = header.split(":")
        if parts and parts[0] == "ClamAV-VDB" and len(parts) >= 8:
            info.update({
                "built": parts[1],
                "version": parts[2],
                "signatures": int(parts[3]),
                "functionality_level": parts[4],
                "builder": parts[7],
            })
    except (OSError, ValueError, IndexError):
        pass
    return info


def read_clamav_status():
    root = Path(os.environ.get("CLAMAV_STATE_PATH", "/data/mail-state"))
    result = {
        "state_path": str(root),
        "state_available": root.exists() and root.is_dir(),
        "databases": [],
        "total_signatures": 0,
        "newest_update": None,
        "freshness": "Unavailable",
    }
    if not result["state_available"]:
        return result

    candidates = []
    for pattern in ("*.cvd", "*.cld", "*.cud"):
        candidates.extend(root.rglob(pattern))

    seen = set()
    for path in sorted(candidates, key=lambda p: p.name.lower()):
        try:
            real = path.resolve()
            if real in seen or not path.is_file():
                continue
            seen.add(real)
            result["databases"].append(_parse_cvd_header(path))
        except OSError:
            continue

    signature_counts = [d["signatures"] for d in result["databases"] if isinstance(d["signatures"], int)]
    result["total_signatures"] = sum(signature_counts)
    if result["databases"]:
        newest = min(result["databases"], key=lambda d: d["age_hours"])
        result["newest_update"] = newest["modified"]
        age = newest["age_hours"]
        result["freshness"] = "Current" if age <= 48 else ("Old" if age <= 168 else "Stale")
    return result
