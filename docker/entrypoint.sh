#!/bin/sh
# Entrypoint of the application container.
#
#   gunicorn        (default) apply database migrations, then serve the app
#   anything else   run it as is, e.g. "python3 manage.py createsuperuser"
set -e

if [ "$1" = "gunicorn" ] && [ "$#" -eq 1 ]; then
    if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
        python3 manage.py migrate --noinput
    fi
    # Cached export pages may predate a database restore or an upgrade.
    rm -rf "${CACHE_DIR:?}"/* 2>/dev/null || true

    # Connections come from the reverse proxy (in practice from Docker's
    # gateway address), so log the client address the proxy reports in
    # X-Real-IP. It is "-" for requests that did not come through the proxy,
    # such as the container health check.
    ACCESS_LOG_FORMAT='%({x-real-ip}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

    exec gunicorn aprs2netportal.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers "${GUNICORN_WORKERS:-2}" \
        --threads "${GUNICORN_THREADS:-4}" \
        --access-logfile - \
        --access-logformat "$ACCESS_LOG_FORMAT" \
        --no-control-socket \
        --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
fi

exec "$@"
