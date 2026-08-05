#!/bin/sh
set -u

CONTROL_DIR="${CONTROL_DIR:-/control}"
REQUEST_FILE="$CONTROL_DIR/fetch-now.request"
STATUS_FILE="$CONTROL_DIR/fetch-now-status.json"
EVENT_FILE="$CONTROL_DIR/poll-events.jsonl"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-180}"

mkdir -p "$CONTROL_DIR"
touch "$EVENT_FILE"
chmod 0644 "$EVENT_FILE"

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

write_status() {
  state="$1"
  message="$2"
  timestamp=$(date -Iseconds)
  tmp="$STATUS_FILE.tmp"
  printf '{\n  "state": "%s",\n  "timestamp": "%s",\n  "message": "%s"\n}\n' \
    "$state" "$timestamp" "$(json_escape "$message")" > "$tmp"
  chmod 0644 "$tmp"
  mv "$tmp" "$STATUS_FILE"
}

write_event() {
  source="$1"
  state="$2"
  process_count="$3"
  message="$4"
  timestamp=$(date -Iseconds)
  printf '{"timestamp":"%s","source":"%s","state":"%s","process_count":%s,"message":"%s"}\n' \
    "$timestamp" "$source" "$state" "$process_count" "$(json_escape "$message")" >> "$EVENT_FILE"
  tail -n 500 "$EVENT_FILE" > "$EVENT_FILE.tmp" 2>/dev/null || true
  mv "$EVENT_FILE.tmp" "$EVENT_FILE" 2>/dev/null || true
  chmod 0644 "$EVENT_FILE"
}

trigger_fetchmail() {
  count=0
  for proc in /proc/[0-9]*; do
    [ -r "$proc/comm" ] || continue
    name=$(cat "$proc/comm" 2>/dev/null || true)
    case "$name" in
      fetchmail*)
        pid=${proc##*/}
        if kill -USR1 "$pid" 2>/dev/null; then
          count=$((count + 1))
        fi
        ;;
    esac
  done
  printf '%s\n' "$count"
}

write_status "starting" "Waiting for Fetchmail to start before the initial mailbox poll."
write_event "startup" "waiting" 0 "Waiting for Fetchmail to start."
echo "MailGate fetch trigger ready"

elapsed=0
startup_done=0
while [ "$elapsed" -lt "$STARTUP_TIMEOUT" ]; do
  count=$(trigger_fetchmail)
  if [ "$count" -gt 0 ]; then
    message="Initial startup poll triggered on $count Fetchmail process(es)."
    write_status "success" "$message"
    write_event "startup" "triggered" "$count" "$message"
    echo "$message"
    startup_done=1
    break
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done

if [ "$startup_done" -eq 0 ]; then
  message="No Fetchmail process appeared within ${STARTUP_TIMEOUT} seconds; initial poll was not triggered."
  write_status "error" "$message"
  write_event "startup" "failed" 0 "$message"
fi

while true; do
  if [ -f "$REQUEST_FILE" ]; then
    rm -f "$REQUEST_FILE"
    count=$(trigger_fetchmail)
    if [ "$count" -gt 0 ]; then
      message="Manual poll triggered on $count Fetchmail process(es)."
      write_status "success" "$message"
      write_event "manual" "triggered" "$count" "$message"
      echo "$message"
    else
      message="No running Fetchmail process was found in the mailserver PID namespace."
      write_status "error" "$message"
      write_event "manual" "failed" 0 "$message"
      echo "$message" >&2
    fi
  fi
  sleep 1
done
