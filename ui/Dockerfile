FROM python:3.13-alpine

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app_clean.py connection_tests.py auth_store.py ./

RUN addgroup -S mailgate && adduser -S -G mailgate mailgate
USER mailgate

EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--access-logfile", "-", "app_clean:app"]
