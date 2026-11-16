#!/usr/bin/env python3
"""Container health check: fetch the login page from the local gunicorn.

Django only answers requests whose Host header is in ALLOWED_HOSTS, so the
request is made under the first configured host name rather than as
127.0.0.1, which would be refused (and reported to ADMINS) in production.
"""
import os
import sys
import urllib.request

hosts = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '').split(',') if h.strip()]
# ".example.com" matches the domain and its subdomains, "*" matches anything
host = hosts[0].lstrip('.') if hosts else 'localhost'
if host in ('', '*'):
    host = 'localhost'

request = urllib.request.Request(
    'http://127.0.0.1:8000/accounts/login/', headers={'Host': host})
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception as e:
    print("health check failed: %s" % e, file=sys.stderr)
    sys.exit(1)
