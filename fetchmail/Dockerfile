FROM alpine:3.22

RUN apk add --no-cache fetchmail ca-certificates tzdata

COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
