import os

import django
from django.urls import resolve

# For testing import time when running 'python manage.py runserver' 
# Run 'python -x importtime it.py'
# - source: https://adamj.eu/tech/2023/03/02/django-profile-and-improve-import-time/

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "thoth.settings")
django.setup()
resolve("/")