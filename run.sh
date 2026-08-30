#!/bin/bash
#
# Development launcher:
#     bash run.sh
#
# Production launcher (ASGI via daphne, no auto-migrations):
#     bash run.sh production
#   or with PRODUCTION=1 set in the environment.
#
# NOTES
#   * Deliberately NEVER runs `makemigrations` — that command generates new
#     migration files, which must be written by a developer and committed to
#     git, never created on a production box.
#   * collectstatic is safe to run repeatedly (idempotent), so it lives here
#     rather than only in production.
#   * /media/ (uploaded photos, PDFs) is served by Django only when DEBUG=True.
#     In production nginx must alias it, e.g.:
#         location /media/ { alias /path/to/media/; }

set -e

# 1. Virtual environment check garne (Local folder mai check garne)
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python -m venv .venv
fi

# 2. Virtual environment activate garne (Windows Git Bash ko lagi)
echo "Activating virtual environment..."
source .venv/Scripts/activate || source .venv/bin/activate

# 3. Pip upgrade ra requirements install garne
echo "Installing dependencies..."
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Django Migrations chalaune (apply committed migrations only)
echo "Running migrations..."
python manage.py migrate

# 5. Static files banaune (production servers run with DEBUG=False, where the
#    dev static handler is off and WhiteNoise serves from STATIC_ROOT)
echo "Collecting static files..."
python manage.py collectstatic --noinput

# 6. Server start garne
if [ "$1" = "production" ] || [ "$PRODUCTION" = "1" ]; then
    echo "Starting daphne (ASGI) on 0.0.0.0:8000..."
    exec daphne -b 0.0.0.0 -p 8000 waste_system.asgi:application
else
    echo "Starting development server..."
    exec python manage.py runserver
fi