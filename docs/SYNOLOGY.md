# Synology deployment

## Requirements

- DSM 7 with Container Manager or Portainer
- At least 2 GB free RAM; 4 GB recommended with ClamAV
- Persistent storage under `/volume1/docker/mailgate`
- Network access from Synology to the Exchange SMTP port

## Installation

```bash
cd /volume1/docker
git clone https://github.com/frazon11/MailGate.git mailgate
cd mailgate
cp .env.example .env
cp fetchmail/fetchmailrc.example fetchmail/fetchmailrc
chmod 600 fetchmail/fetchmailrc
mkdir -p postfix/spool redis/data clamav/database
```

Edit `.env` and `fetchmail/fetchmailrc`, then start:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f
```

## Testing sequence

1. Keep the `keep` option enabled in Fetchmail.
2. Use one test mailbox and one Exchange recipient.
3. Confirm a clean message arrives.
4. Stop Exchange temporarily and confirm mail remains in the Postfix queue.
5. Start Exchange and confirm queued delivery resumes.
6. Test spam tagging and the EICAR antivirus test file in an isolated test environment.
7. Only after successful testing, consider changing `keep` to `no keep`.

## Useful commands

```bash
docker compose logs -f fetchmail
docker compose logs -f postfix
docker compose exec postfix postqueue -p
docker compose exec postfix postqueue -f
docker compose exec rspamd rspamc stat
```

Do not expose Redis, ClamAV or Rspamd ports to the LAN or internet.
