FROM alpine:3.22

RUN apk add --no-cache postfix postfix-pcre ca-certificates tzdata bash

COPY main.cf.template /etc/postfix/main.cf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

EXPOSE 25
ENTRYPOINT ["/entrypoint.sh"]
