FROM python:3.13-alpine

WORKDIR /app
COPY fetcher.py /app/fetcher.py

RUN addgroup -S mailgate && adduser -S -G mailgate mailgate \
    && mkdir -p /control /state \
    && chown -R mailgate:mailgate /control /state

USER mailgate
ENTRYPOINT ["python", "-u", "/app/fetcher.py"]
