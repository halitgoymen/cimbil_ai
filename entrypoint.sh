#!/bin/bash
set -e

# 1. Download missing data from Google Drive
echo "=== Gymble Startup ==="
python /app/download_data.py

# 2. Run Unified ASGI application
echo "Starting Unified ASGI Server on Port ${PORT:-7860}"
exec python /app/run_combined.py
