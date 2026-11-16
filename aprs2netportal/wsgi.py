"""WSGI entry point for the aprs2netportal project."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aprs2netportal.settings")

application = get_wsgi_application()
