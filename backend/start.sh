#!/bin/sh
# Catalyst AppSail startup script.
# Install deps then start uvicorn on the Catalyst-assigned port.
PORT=${X_ZOHO_CATALYST_LISTEN_PORT:-9000}
pip install -r requirements.txt --quiet 2>/dev/null
exec python -m uvicorn main:app --host 0.0.0.0 --port "$PORT"
