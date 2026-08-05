#!/bin/sh
set -u

CONTROL_DIR="${CONTROL_DIR:-/control}"
REQUEST_FILE="$CONTROL_DIR/fetch-now.request"
STATUS_FILE="$CONTROL_DIR/fetch-now-status.json"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-180}"

mkdir -p "$CONTROL_DIR"

write_status() {
  state="$1"
  message="$2"
  timestamp=$(date -Iseconds)
  tmp="$STATUS_FILE.tmp"
  printf '{\n  "state": "%s",\n  "timestamp": "%s",\n  "message": "%s"\n}\n' \
    "$state" "$timestamp" "$(printf '%s' "$message" | sed 's/\\/\\\\/g; s/"/\\"/g')" > "$tmp"
  chmod 0644 "$tmp"
  mv "$tmp" "$STATUS_FILE"
}

trigger_fetchmail() {
  count=0
  for proc in /proc/[0-9]*; do
    [ -r "$proc/comm" ] || continue
    name=$(cat "$proc/comm" 2>/dev/null || true)
    if [ "$name" = "fetchmail" ]; then
      pid=${proc##*/}
      if kill -USR1 "$pid" 2>/dev/null; then
        count=$((count + 1))
      fi
    fi
  done
  printf '%s\n' "$count"
}

write_status "starting" "Waiting for Fetchmail to start before the initial mailbox poll."
echo "MailGate fetch trigger ready"

elapsed=0
startup_done=0
while [ "$elapsed" -lt "$STARTUP_TIMEOUT" ]; do
  count=$(trigger_fetchmail)
  if [ "$count" -gt 0 ]; then
    write_status "success" "Initial startup poll triggered on $count Fetchmail process(es)."
    echo "Initial mailbox poll triggered on $count Fetchmail process(es)"
    startup_done=1
    break
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done

if [ "$startup_done" -eq 0 ]; then
  write_status "error" "No Fetchmail process appeared within ${STARTUP_TIMEOUT} seconds; initial poll was not triggered."
fi

while true; do
  if [ -f "$REQUEST_FILE" ]; then
    rm -f "$REQUEST_FILE"
    count=$(trigger_fetchmail)
    if [ "$count" -gt 0 ]; then
      write_status "success" "Manual poll triggered on $count Fetchmail process(es)."
    else
      write_status "error" "No running Fetchmail process was found in the mailserver PID namespace."
    fi
  fi
  sleep 1
done
