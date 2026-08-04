FROM python:3.13-alpine

ARG MAILGATE_VERSION=0.1.0
ARG MAILGATE_BUILD=dev

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app_v2.py connection_tests.py ./

RUN python - <<'PY'
from pathlib import Path
path = Path('/app/app_v2.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
    '<h1>MailGate</h1>',
    '<h1>MailGate <span style="font-size:.45em;color:#9ca3af;font-weight:500">v${MAILGATE_VERSION} · build ${MAILGATE_BUILD}</span></h1>',
    1,
)
path.write_text(text, encoding='utf-8')
PY

RUN addgroup -S mailgate && adduser -S -G mailgate mailgate
USER mailgate

EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--access-logfile", "-", "app_v2:app"]
