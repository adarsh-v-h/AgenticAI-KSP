# Backend dev container — Python 3.10 (matches Catalyst AppSail python_3_10 stack)
FROM python:3.10-slim

WORKDIR /app

# Install system deps for cryptography wheel + aiomysql
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && rm -rf /var/lib/apt/lists/*

# Install Python deps (from the backend-specific requirements + test deps)
COPY backend/requirements.txt /tmp/requirements.txt
COPY requirements.txt /tmp/requirements-test.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/requirements-test.txt

# Source code is mounted as a volume in docker-compose (hot-reload)
COPY backend/ /app/

EXPOSE 8000
