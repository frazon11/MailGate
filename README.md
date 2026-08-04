# MailGate

MailGate is an open-source Docker gateway that retrieves messages from external IMAP or POP3 mailboxes, scans them for spam and malware, then forwards them by SMTP to an existing on-premises Microsoft Exchange server.

## Architecture

MailGate now uses two containers:

- `mailgate-mailserver`: Docker Mailserver with Fetchmail, Postfix, Rspamd, internal Redis and ClamAV.
- `mailgate-ui`: a small WebUI for managing provider mailboxes and fixed Exchange recipient mappings.

```text
External IMAP/POP3 provider
            |
            v
        Fetchmail
            |
            v
 Postfix + Rspamd + ClamAV
            |
            v
 On-premises Exchange Receive Connector
```

No SMTP, IMAP or POP port is published to the internet. Only the WebUI port is published to the trusted LAN.

## Features

- Multiple provider mailboxes
- IMAP and POP3 over TLS
- Fixed provider-account to Exchange-recipient mapping
- Keep or delete source messages after successful downstream acceptance
- Rspamd spam and phishing analysis
- ClamAV malware scanning
- Internal Redis for Rspamd
- Persistent Postfix queue and logs
- SMTP relay to an existing Exchange Receive Connector
- Basic-authenticated WebUI
- Synology and Portainer compatible

## Portainer deployment

Create a Git-based stack with:

```text
Repository URL: https://github.com/frazon11/MailGate.git
Repository reference: refs/heads/main
Compose path: docker-compose.yml
```

Add these environment variables in Portainer:

```env
DATA_PATH=/volume1/docker/MailGate
TZ=Europe/Brussels
MAILGATE_HOSTNAME=mailgate.local
EXCHANGE_HOST=192.168.177.13
EXCHANGE_PORT=25
FETCHMAIL_POLL_INTERVAL=60
WEB_PORT=8795
UI_USERNAME=admin
UI_PASSWORD=replace-with-a-strong-password
```

Portainer/Docker creates the bind-mount directories automatically. To create them manually:

```bash
sudo mkdir -p \
  /volume1/docker/MailGate/config \
  /volume1/docker/MailGate/mail-data \
  /volume1/docker/MailGate/mail-state \
  /volume1/docker/MailGate/mail-logs
```

After deployment, open:

```text
http://SYNOLOGY-IP:8795
```

Log in with `UI_USERNAME` and `UI_PASSWORD`, then add the provider mailboxes. The UI writes:

```text
/volume1/docker/MailGate/config/mailgate.json
/volume1/docker/MailGate/config/fetchmail.cf
```

Docker Mailserver polls the shared configuration directory and applies changes automatically.

## Safe first test

The WebUI enables **Keep messages at provider** by default. Leave that enabled until all of the following have been verified:

1. Retrieval succeeds.
2. Rspamd and ClamAV process the message.
3. Exchange accepts it.
4. A stopped Exchange server causes Postfix to queue and retry delivery.
5. Restarting the stack does not lose queued mail.

Only then disable source retention for the mailbox.

## Exchange

Create a dedicated Exchange Receive Connector that accepts SMTP from the Synology host IP. Restrict it to that source IP and do not enable unrestricted anonymous relay unless it is genuinely required.

See [`docs/EXCHANGE.md`](docs/EXCHANGE.md) for the Exchange-side configuration notes.

## Persistent data

All runtime data is controlled by one variable:

```env
DATA_PATH=/volume1/docker/MailGate
```

Resulting layout:

```text
/volume1/docker/MailGate/
├── config/
│   ├── fetchmail.cf
│   └── mailgate.json
├── mail-data/
├── mail-state/
└── mail-logs/
```

## Security notes

- Provider passwords are stored locally in `mailgate.json` and `fetchmail.cf`; both are created with mode `0600`.
- Never commit those generated files to GitHub.
- Change the default WebUI password before deployment.
- Publish the WebUI only on a trusted internal network or place it behind an authenticated HTTPS reverse proxy.
- Ordinary spam is tagged with `[SPAM]` instead of being silently deleted during the initial version.

## Status

This is an early functional baseline. Test with non-production mailboxes before using it for business-critical mail.

## License

MIT
