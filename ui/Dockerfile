FROM python:3.13-alpine

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

# Runs as root so the first deployment can initialize a root-owned Synology
# bind mount. The service is only intended for the trusted internal LAN.
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--access-logfile", "-", "app:app"]
