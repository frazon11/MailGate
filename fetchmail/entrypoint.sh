#!/bin/sh
set -eu

CONFIG=/etc/fetchmailrc
INTERVAL=${FETCHMAIL_POLL_INTERVAL:-60}

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: $CONFIG does not exist. Copy fetchmailrc.example to fetchmailrc and configure it." >&2
  exit 1
fi

chmod 600 "$CONFIG" 2>/dev/null || true

exec fetchmail --nodetach --verbose --syslog --set-daemon "$INTERVAL" -f "$CONFIG"
