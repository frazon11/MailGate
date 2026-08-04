#!/bin/sh
set -u

CONTROL_DIR="${CONTROL_DIR:-/control}"
REQUEST_FILE="$CONTROL_DIR/fetch-now.request"
STATUS_FILE="$CONTROL_DIR/fetch-now-status.json"

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

write_status "idle" "Waiting for a fetch request."
echo "MailGate fetch trigger ready"

while true; do
  if [ -f "$REQUEST_FILE" ]; then
    rm -f "$REQUEST_FILE"
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

    if [ "$count" -gt 0 ]; then
      write_status "success" "Triggered immediate polling on $count Fetchmail process(es)."
    else
      write_status "error" "No running Fetchmail process was found in the mailserver PID namespace."
    fi
  fi
  sleep 1
done
