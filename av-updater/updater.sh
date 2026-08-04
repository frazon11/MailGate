#!/bin/sh
set -u

CONTROL_DIR="${CONTROL_DIR:-/control}"
STATE_ROOT="${CLAMAV_STATE_ROOT:-/var/mail-state}"
CLAMAV_UID="${CLAMAV_UID:-100}"
CLAMAV_GID="${CLAMAV_GID:-101}"
REQUEST_FILE="$CONTROL_DIR/av-update.request"
STATUS_FILE="$CONTROL_DIR/av-update-status.json"
LOG_FILE="$CONTROL_DIR/av-update.log"

mkdir -p "$CONTROL_DIR"

json_escape() {
  sed 's/\\/\\\\/g; s/"/\\"/g; s/\r//g' | awk 'BEGIN{ORS="\\n"}{printf "%s\\n",$0}' | sed 's/\\n$//'
}

write_status() {
  state="$1"
  started="$2"
  finished="$3"
  exit_code="$4"
  message="$5"
  escaped_message=$(printf '%s' "$message" | json_escape)
  tmp="$STATUS_FILE.tmp"
  cat > "$tmp" <<EOF
{
  "state": "$state",
  "started_at": "$started",
  "finished_at": "$finished",
  "exit_code": $exit_code,
  "message": "$escaped_message"
}
EOF
  chmod 0664 "$tmp"
  mv "$tmp" "$STATUS_FILE"
}

find_database_dir() {
  found=$(find "$STATE_ROOT" -type f \( -name 'daily.cvd' -o -name 'daily.cld' -o -name 'main.cvd' -o -name 'main.cld' \) -print 2>/dev/null | head -n 1 || true)
  if [ -n "$found" ]; then
    dirname "$found"
    return 0
  fi

  fallback="$STATE_ROOT/lib-clamav"
  mkdir -p "$fallback"
  printf '%s\n' "$fallback"
}

prepare_database_dir() {
  database_dir="$1"
  mkdir -p "$database_dir"

  # FreshClam drops privileges to its internal clamav account. The persistent
  # Synology bind mount must therefore be writable by that numeric UID/GID.
  chown -R "$CLAMAV_UID:$CLAMAV_GID" "$database_dir"
  chmod 0775 "$database_dir"
  find "$database_dir" -type d -exec chmod 0775 {} \; 2>/dev/null || true
  find "$database_dir" -type f -exec chmod 0664 {} \; 2>/dev/null || true
}

write_status "idle" "" "" 0 "Waiting for an update request."

echo "MailGate AV updater ready; watching $REQUEST_FILE"

while true; do
  if [ -f "$REQUEST_FILE" ]; then
    rm -f "$REQUEST_FILE"
    started=$(date -Iseconds)
    database_dir=$(find_database_dir)

    if ! prepare_database_dir "$database_dir" > "$LOG_FILE" 2>&1; then
      rc=$?
      finished=$(date -Iseconds)
      tail_output=$(tail -n 30 "$LOG_FILE" 2>/dev/null || true)
      write_status "error" "$started" "$finished" "$rc" "Could not prepare ClamAV database directory $database_dir.\n$tail_output"
      sleep 2
      continue
    fi

    write_status "running" "$started" "" 0 "Updating ClamAV signatures in $database_dir"
    : > "$LOG_FILE"
    chmod 0664 "$LOG_FILE"

    freshclam --verbose --datadir="$database_dir" > "$LOG_FILE" 2>&1
    rc=$?
    finished=$(date -Iseconds)
    tail_output=$(tail -n 40 "$LOG_FILE" 2>/dev/null || true)

    if [ "$rc" -eq 0 ]; then
      write_status "success" "$started" "$finished" "$rc" "$tail_output"
    else
      write_status "error" "$started" "$finished" "$rc" "$tail_output"
    fi
  fi
  sleep 2
done
