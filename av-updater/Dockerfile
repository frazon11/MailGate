FROM alpine:3.22

RUN apk add --no-cache clamav clamav-libunrar freshclam ca-certificates tzdata

COPY updater.sh /usr/local/bin/mailgate-av-updater
RUN chmod 0755 /usr/local/bin/mailgate-av-updater

ENTRYPOINT ["/usr/local/bin/mailgate-av-updater"]
