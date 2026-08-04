FROM python:3.13-alpine

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app_clean.py bootstrap.py fetch_now_bootstrap.py fetch_now.py account_folders.py activity_log.py av_status.py av_update.py rspamd_config_fix.py connection_tests.py auth_store.py ./

RUN addgroup -S mailgate && adduser -S -G mailgate mailgate
USER mailgate

EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--access-logfile", "-", "fetch_now_bootstrap:app"]
