import imaplib
import os
import poplib
import smtplib
import ssl

TIMEOUT = 15


def _tls_context(verify_certificate=True):
    if verify_certificate:
        return ssl.create_default_context()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def test_provider(host, port, protocol, username, password, verify_certificate=True):
    context = _tls_context(verify_certificate)
    if protocol == "imap":
        client = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=TIMEOUT)
        try:
            # imaplib defaults to ASCII for commands. Some providers accept UTF-8
            # mailbox credentials, so explicitly encode LOGIN commands as UTF-8.
            client._encoding = "utf-8"
            client.login(username, password)
            status, data = client.select("INBOX", readonly=True)
            count = data[0].decode(errors="replace") if status == "OK" and data else "unknown"
            suffix = " Certificate verification was disabled." if not verify_certificate else ""
            return f"Provider login successful. INBOX is accessible; message count: {count}.{suffix}"
        finally:
            try:
                client.logout()
            except Exception:
                pass

    client = poplib.POP3_SSL(host, port, context=context, timeout=TIMEOUT)
    try:
        client.encoding = "utf-8"
        client.user(username)
        client.pass_(password)
        count, size = client.stat()
        suffix = " Certificate verification was disabled." if not verify_certificate else ""
        return f"Provider login successful. POP3 reports {count} messages and {size} bytes.{suffix}"
    finally:
        try:
            client.quit()
        except Exception:
            pass


def test_exchange(recipient):
    host = os.environ.get("EXCHANGE_HOST", "").strip()
    if not host:
        raise ValueError("EXCHANGE_HOST is not configured.")
    port = int(os.environ.get("EXCHANGE_PORT", "25"))
    sender = os.environ.get("TEST_SENDER", "mailgate-test@localhost")

    client = smtplib.SMTP(host, port, timeout=TIMEOUT)
    try:
        code, reply = client.ehlo("mailgate-test")
        if code >= 400:
            raise RuntimeError(f"EHLO rejected: {code} {reply.decode(errors='replace')}")
        code, reply = client.mail(sender)
        if code >= 400:
            raise RuntimeError(f"MAIL FROM rejected: {code} {reply.decode(errors='replace')}")
        code, reply = client.rcpt(recipient)
        reply_text = reply.decode(errors="replace")
        client.rset()
        if code not in {250, 251, 252}:
            raise RuntimeError(f"Recipient rejected: {code} {reply_text}")
        return f"Exchange accepted {recipient} with SMTP response {code}. No message was sent."
    finally:
        try:
            client.quit()
        except Exception:
            client.close()
