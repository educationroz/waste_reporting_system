#!/bin/bash

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

# 4. Django Migrations chalaune
echo "Running migrations..."
python manage.py makemigrations
python manage.py migrate

# 5. Server start garne
echo "Starting server..."
python manage.py runserver