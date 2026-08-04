FROM python:3.13-alpine

ARG MAILGATE_VERSION=0.1.2
ARG MAILGATE_BUILD=hotfix

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app_v2.py connection_tests.py auth_store.py filter_settings.py apply_admin_password_patch.py apply_logs_patch.py apply_filter_settings_patch.py ./

RUN python /app/apply_admin_password_patch.py \
 && python /app/apply_logs_patch.py \
 && python /app/apply_filter_settings_patch.py \
 && rm /app/apply_admin_password_patch.py /app/apply_logs_patch.py /app/apply_filter_settings_patch.py

RUN sed -i "s|<h1>MailGate</h1>|<h1>MailGate <span style=\"font-size:.45em;color:#9ca3af;font-weight:500\">v${MAILGATE_VERSION} · build ${MAILGATE_BUILD}</span></h1>|" /app/app_v2.py

RUN addgroup -S mailgate && adduser -S -G mailgate mailgate
USER mailgate

EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--access-logfile", "-", "app_v2:app"]
