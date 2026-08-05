"""Runtime compatibility patches for the MailGate fetcher."""

import imaplib

_ORIGINAL_LOGIN = imaplib.IMAP4.login


def _contains_non_ascii(value):
    try:
        str(value).encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def _utf8_login(self, user, password):
    """Use SASL PLAIN when IMAP credentials cannot be represented as ASCII.

    Python's imaplib LOGIN command encodes command arguments as ASCII. Provider
    passwords may legitimately contain characters such as Ö, ä or €. SASL
    PLAIN carries the authentication payload as UTF-8 bytes and imaplib handles
    the required base64 transport encoding.
    """
    if not (_contains_non_ascii(user) or _contains_non_ascii(password)):
        return _ORIGINAL_LOGIN(self, user, password)

    payload = ("\0" + str(user) + "\0" + str(password)).encode("utf-8")

    try:
        return self.authenticate("PLAIN", lambda _challenge: payload)
    except imaplib.IMAP4.error as exc:
        raise imaplib.IMAP4.error(
            "IMAP server rejected UTF-8 SASL PLAIN authentication"
        ) from exc


imaplib.IMAP4.login = _utf8_login
