#!/bin/sh
set -eu

: "${EXCHANGE_HOST:?EXCHANGE_HOST must be set}"
: "${ALLOWED_RECIPIENT_DOMAINS:?ALLOWED_RECIPIENT_DOMAINS must be set}"

export MAILGATE_HOSTNAME=${MAILGATE_HOSTNAME:-mailgate.local}
export EXCHANGE_PORT=${EXCHANGE_PORT:-25}

envsubst < /etc/postfix/main.cf.template > /etc/postfix/main.cf

postfix check
exec postfix start-fg
