FROM alpine:3.22

COPY trigger.sh /usr/local/bin/mailgate-fetch-trigger
RUN chmod 0755 /usr/local/bin/mailgate-fetch-trigger

ENTRYPOINT ["/usr/local/bin/mailgate-fetch-trigger"]
