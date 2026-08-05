#!/usr/bin/env python3
import email
import imaplib
import json
import os
import poplib
import smtplib
import sqlite3
import ssl
import time
import traceback
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

CONFIG_FILE = Path(os.environ.get("MAILGATE_CONFIG", "/config/mailgate.json"))
CONTROL_DIR = Path(os.environ.get("CONTROL_DIR", "/control"))
REQUEST_FILE = CONTROL_DIR / "fetch-now.request"
EVENT_FILE = CONTROL_DIR / "mail-flow.jsonl"
STATUS_FILE = CONTROL_DIR / "fetcher-status.json"
STATE_DB = Path(os.environ.get("STATE_DB", "/state/fetcher.sqlite3"))
SMTP_HOST = os.environ.get("SMTP_HOST", "mailserver")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
DEFAULT_INTERVAL = int(os.environ.get("DEFAULT_POLL_INTERVAL", "60"))
MAX_EVENT_BYTES = int(os.environ.get("MAX_EVENT_BYTES", str(5 * 1024 * 1024)))

CONTROL_DIR.mkdir(parents=True, exist_ok=True)
STATE_DB.parent.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def clean(value, limit=300):
    text = "" if value is None else str(value)
    return text.replace("\r", " ").replace("\n", " ")[:limit]


def write_json_atomic(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def emit(event, **fields):
    record = {"time": now(), "event": event, **{k: clean(v, 1000) for k, v in fields.items()}}
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with EVENT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line)
    try:
        if EVENT_FILE.stat().st_size > MAX_EVENT_BYTES:
            lines = EVENT_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
            EVENT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    print(line.rstrip(), flush=True)


def status(state, message, **extra):
    write_json_atomic(STATUS_FILE, {"state": state, "timestamp": now(), "message": message, **extra})


def db():
    connection = sqlite3.connect(STATE_DB)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS delivered (account_key TEXT NOT NULL, folder TEXT NOT NULL, remote_id TEXT NOT NULL, delivered_at TEXT NOT NULL, PRIMARY KEY(account_key, folder, remote_id))"
    )
    connection.commit()
    return connection


def delivered(connection, account_key, folder, remote_id):
    return connection.execute(
        "SELECT 1 FROM delivered WHERE account_key=? AND folder=? AND remote_id=?",
        (account_key, folder, remote_id),
    ).fetchone() is not None


def mark_delivered(connection, account_key, folder, remote_id):
    connection.execute(
        "INSERT OR REPLACE INTO delivered(account_key, folder, remote_id, delivered_at) VALUES(?,?,?,?)",
        (account_key, folder, remote_id, now()),
    )
    connection.commit()


def load_settings():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("configuration root is not an object")
        return data
    except Exception as exc:
        emit("configuration_error", result="failed", detail=exc)
        return {"accounts": [], "delivery": {"poll_interval": DEFAULT_INTERVAL}}


def account_key(account):
    return "|".join(
        clean(account.get(name, ""), 200)
        for name in ("protocol", "host", "port", "username", "recipient")
    )


def tls_context(verify):
    if verify:
        return ssl.create_default_context()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def message_metadata(raw):
    try:
        msg = BytesParser(policy=default).parsebytes(raw, headersonly=True)
        sender = msg.get("From", "")
        subject = msg.get("Subject", "")
        message_id = msg.get("Message-ID", "")
        envelope = email.utils.parseaddr(sender)[1] or "mailgate-fetcher@localhost"
        return envelope, sender, subject, message_id
    except Exception:
        return "mailgate-fetcher@localhost", "", "", ""


def submit(raw, recipient, context):
    envelope, sender, subject, message_id = message_metadata(raw)
    emit("smtp_submit_start", result="started", recipient=recipient, sender=sender, subject=subject, message_id=message_id, **context)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
        smtp.ehlo_or_helo_if_needed()
        refused = smtp.sendmail(envelope, [recipient], raw)
        if refused:
            raise RuntimeError(f"SMTP recipient refused: {refused}")
    emit("smtp_accepted", result="accepted", recipient=recipient, sender=sender, subject=subject, message_id=message_id, **context)
    return sender, subject, message_id


def poll_imap(account, connection, run_id):
    host = account["host"]
    port = int(account.get("port", 993))
    username = account["username"]
    recipient = account["recipient"]
    keep = bool(account.get("keep", True))
    verify = bool(account.get("verify_certificate", True))
    folders = account.get("folders") or ["INBOX"]
    key = account_key(account)
    base = {"run_id": run_id, "protocol": "imap", "account": username, "host": host}
    emit("mailbox_connect", result="started", **base)
    client = imaplib.IMAP4_SSL(host, port, ssl_context=tls_context(verify), timeout=60)
    try:
        client.login(username, account["password"])
        emit("mailbox_login", result="success", **base)
        for folder in folders:
            folder = str(folder or "INBOX")
            selected, data = client.select(folder, readonly=False)
            if selected != "OK":
                raise RuntimeError(f"Cannot select folder {folder}: {data}")
            count = int(data[0] or 0)
            emit("folder_check", result="success", folder=folder, messages=count, **base)
            typ, data = client.uid("search", None, "ALL")
            if typ != "OK":
                raise RuntimeError(f"UID search failed for {folder}: {data}")
            uids = [item.decode("ascii", errors="ignore") for item in (data[0] or b"").split()]
            pending = [uid for uid in uids if not delivered(connection, key, folder, uid)]
            emit("messages_found", result="success", folder=folder, messages=len(pending), total=count, **base)
            for uid in pending:
                context = {**base, "folder": folder, "remote_id": uid}
                typ, fetched = client.uid("fetch", uid, "(RFC822)")
                if typ != "OK":
                    raise RuntimeError(f"UID fetch failed for {folder}/{uid}: {fetched}")
                raw = next((part[1] for part in fetched if isinstance(part, tuple) and len(part) > 1), None)
                if not raw:
                    raise RuntimeError(f"No RFC822 payload returned for {folder}/{uid}")
                emit("message_fetched", result="success", bytes=len(raw), **context)
                sender, subject, message_id = submit(raw, recipient, context)
                mark_delivered(connection, key, folder, uid)
                if keep:
                    client.uid("store", uid, "+FLAGS.SILENT", "(\\Seen)")
                    emit("source_retained", result="success", sender=sender, subject=subject, message_id=message_id, **context)
                else:
                    typ, response = client.uid("store", uid, "+FLAGS.SILENT", "(\\Deleted)")
                    if typ != "OK":
                        raise RuntimeError(f"Could not mark {folder}/{uid} deleted: {response}")
                    client.expunge()
                    emit("source_deleted", result="success", sender=sender, subject=subject, message_id=message_id, **context)
    finally:
        try:
            client.logout()
        except Exception:
            pass


def poll_pop3(account, connection, run_id):
    host = account["host"]
    port = int(account.get("port", 995))
    username = account["username"]
    recipient = account["recipient"]
    keep = bool(account.get("keep", True))
    verify = bool(account.get("verify_certificate", True))
    key = account_key(account)
    folder = "INBOX"
    base = {"run_id": run_id, "protocol": "pop3", "account": username, "host": host}
    emit("mailbox_connect", result="started", **base)
    client = poplib.POP3_SSL(host, port, context=tls_context(verify), timeout=60)
    try:
        client.user(username)
        client.pass_(account["password"])
        emit("mailbox_login", result="success", **base)
        count, _ = client.stat()
        emit("folder_check", result="success", folder=folder, messages=count, **base)
        uid_rows = client.uidl()[1]
        pending = []
        for row in uid_rows:
            number, remote_id = row.decode("utf-8", errors="replace").split(maxsplit=1)
            if not delivered(connection, key, folder, remote_id):
                pending.append((int(number), remote_id))
        emit("messages_found", result="success", folder=folder, messages=len(pending), total=count, **base)
        for number, remote_id in pending:
            context = {**base, "folder": folder, "remote_id": remote_id}
            _, lines, _ = client.retr(number)
            raw = b"\r\n".join(lines) + b"\r\n"
            emit("message_fetched", result="success", bytes=len(raw), **context)
            sender, subject, message_id = submit(raw, recipient, context)
            mark_delivered(connection, key, folder, remote_id)
            if keep:
                emit("source_retained", result="success", sender=sender, subject=subject, message_id=message_id, **context)
            else:
                client.dele(number)
                emit("source_deleted", result="success", sender=sender, subject=subject, message_id=message_id, **context)
    finally:
        try:
            client.quit()
        except Exception:
            pass


def poll_once(reason):
    run_id = f"{int(time.time())}-{os.getpid()}"
    settings = load_settings()
    accounts = settings.get("accounts") or []
    emit("poll_started", result="started", reason=reason, run_id=run_id, accounts=len(accounts))
    failures = 0
    connection = db()
    try:
        for index, account in enumerate(accounts):
            protocol = str(account.get("protocol", "imap")).lower()
            try:
                required = ("host", "username", "password", "recipient")
                missing = [field for field in required if not account.get(field)]
                if missing:
                    raise ValueError("missing fields: " + ", ".join(missing))
                if protocol == "imap":
                    poll_imap(account, connection, run_id)
                elif protocol == "pop3":
                    poll_pop3(account, connection, run_id)
                else:
                    raise ValueError(f"unsupported protocol: {protocol}")
            except Exception as exc:
                failures += 1
                emit(
                    "account_error",
                    result="failed",
                    run_id=run_id,
                    account_index=index,
                    account=account.get("username", ""),
                    host=account.get("host", ""),
                    protocol=protocol,
                    detail=exc,
                )
                traceback.print_exc()
    finally:
        connection.close()
    result = "failed" if failures else "success"
    message = f"Poll completed: {len(accounts)} account(s), {failures} failure(s)."
    emit("poll_finished", result=result, reason=reason, run_id=run_id, accounts=len(accounts), failures=failures)
    status(result, message, run_id=run_id, reason=reason, failures=failures)


def interval_seconds():
    settings = load_settings()
    try:
        return max(10, min(86400, int(settings.get("delivery", {}).get("poll_interval", DEFAULT_INTERVAL))))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL


def main():
    status("starting", "Dedicated MailGate fetcher is starting.")
    emit("fetcher_started", result="success")
    poll_once("startup")
    next_poll = time.monotonic() + interval_seconds()
    while True:
        if REQUEST_FILE.exists():
            try:
                REQUEST_FILE.unlink()
            except FileNotFoundError:
                pass
            poll_once("manual")
            next_poll = time.monotonic() + interval_seconds()
        if time.monotonic() >= next_poll:
            poll_once("scheduled")
            next_poll = time.monotonic() + interval_seconds()
        time.sleep(1)


if __name__ == "__main__":
    main()
