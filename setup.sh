#!/usr/bin/env python
"""
setup.py — One-shot bootstrap script for local development.
Run:  python setup.py
It will:
  1. Apply migrations
  2. Create a default admin user  (username: admin  / password: admin123)
  3. Create a default regular user (username: user1  / password: user1234)
  4. Seed 3 sample reports
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'waste_project.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.core.management import call_command
from reports.models import User, Report

print("→ Running migrations…")
call_command('migrate', verbosity=0)

print("→ Creating users…")
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(
        username='admin', email='admin@example.com',
        password='admin123', role='admin',
    )
    print("   ✓ Admin created  (admin / admin123)")
else:
    print("   ⚠ Admin already exists")

if not User.objects.filter(username='user1').exists():
    User.objects.create_user(
        username='user1', email='user1@example.com',
        password='user1234', role='user',
    )
    print("   ✓ Regular user created  (user1 / user1234)")
else:
    print("   ⚠ user1 already exists")

user1 = User.objects.get(username='user1')

print("→ Seeding sample reports…")
samples = [
    {
        'title': 'Illegal dumping near river bank',
        'description': 'Large pile of construction waste illegally dumped near the river bank. Hazardous materials visible.',
        'latitude': 28.2096, 'longitude': 83.9856, 'status': 'pending',
    },
    {
        'title': 'Overflowing bin at market',
        'description': 'Public bin at the central market has been overflowing for 3 days. Attracting insects.',
        'latitude': 28.2150, 'longitude': 83.9900, 'status': 'in_progress',
    },
    {
        'title': 'Plastic waste on hiking trail',
        'description': 'Trail to the viewpoint littered with plastic bottles and food wrappers left by tourists.',
        'latitude': 28.2200, 'longitude': 83.9800, 'status': 'solved',
    },
]
for s in samples:
    Report.objects.get_or_create(title=s['title'], defaults={**s, 'user': user1})
print(f"   ✓ {len(samples)} sample reports seeded")

print("\n✅ Setup complete! Run:  python manage.py runserver")
print("   Admin dashboard → http://127.0.0.1:8000/dashboard/")
print("   Map view        → http://127.0.0.1:8000/map/")