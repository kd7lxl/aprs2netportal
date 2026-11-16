# aprs2netportal application image.
#
# All dependencies come from the Ubuntu archive, so security updates arrive by
# rebuilding the image (docker compose build --pull).
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3 \
        python3-django \
        python3-psycopg \
        python3-whitenoise \
        libjs-jquery \
        gunicorn \
        tzdata \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 990 --user-group --home-dir /app --shell /usr/sbin/nologin portal \
 && install -d -o portal -g portal /var/cache/portal

WORKDIR /app
COPY manage.py ./
COPY aprs2netportal ./aprs2netportal
COPY sysop ./sysop
COPY lotwauth ./lotwauth
COPY utils ./utils
COPY templates ./templates
COPY assets ./assets
COPY docker/entrypoint.sh /usr/local/bin/portal-entrypoint
COPY docker/healthcheck.py /usr/local/bin/portal-healthcheck

# Collect and compress static files into the image; WhiteNoise serves them.
RUN SECRET_KEY=build-time-only python3 manage.py collectstatic --noinput \
 && python3 -m compileall -q .

ENV CACHE_DIR=/var/cache/portal \
    GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=4

USER portal
EXPOSE 8000

ENTRYPOINT ["portal-entrypoint"]
CMD ["gunicorn"]
