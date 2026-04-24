#!/bin/bash
set -e
mkdir -p /app/data
python manage.py migrate --database=default 2>/dev/null || true
python manage.py migrate --database=local    2>/dev/null || true
exec python manage.py runserver 0.0.0.0:8000
