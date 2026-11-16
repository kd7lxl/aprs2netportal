# PostgreSQL image for the portal: the official PostgreSQL image plus pghoard.
#
# The same image runs both the database server ("db" service) and the backup
# daemon ("pghoard" service). pghoard needs pg_basebackup and pg_receivewal of
# exactly the server's major version, and the server needs pghoard's
# pghoard_postgres_command to fetch WAL when restoring a backup, so they are
# kept in one image and upgraded together.
ARG POSTGRES_VERSION=18

FROM postgres:${POSTGRES_VERSION} AS pghoard-build
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3-venv python3-dev gcc g++ pkg-config git ca-certificates \
        libsystemd-dev libsnappy-dev \
 && rm -rf /var/lib/apt/lists/*
# pghoard is not released on PyPI any more (the version there is obsolete), so
# it is installed from git. Pinned to a commit rather than the 2.8.0 tag,
# which fails with pydantic 2 ("cannot pickle '_thread.lock' object" on every
# upload); fixed on master. Move to the next release tag once there is one.
ARG PGHOARD_VERSION=93d9010580bed65a27e2204e15a2102d2564e19a
# Everything pghoard pulls in from PyPI is held to the versions in
# constraints.txt; a package missing from that file fails the check below.
COPY constraints.txt /tmp/constraints.txt
RUN python3 -m venv /opt/pghoard \
 && /opt/pghoard/bin/pip install --no-cache-dir \
        --constraint /tmp/constraints.txt \
        "pghoard @ git+https://github.com/Aiven-Open/pghoard.git@${PGHOARD_VERSION}" \
        botocore packaging \
 && /opt/pghoard/bin/pip freeze --exclude pghoard | sort > /tmp/installed.txt \
 && grep -v '^#' /tmp/constraints.txt | grep . | sort > /tmp/expected.txt \
 && diff /tmp/expected.txt /tmp/installed.txt

FROM postgres:${POSTGRES_VERSION}
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3 libsnappy1v5 libsystemd0 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=pghoard-build /opt/pghoard /opt/pghoard
# All pghoard commands on PATH; pghoard_restore needs pghoard_gnutaremu and the
# database server needs pghoard_postgres_command.
RUN ln -s /opt/pghoard/bin/pghoard* /usr/local/bin/ \
 && install -d -o postgres -g postgres -m 0700 /var/lib/pghoard
COPY initdb.d/ /docker-entrypoint-initdb.d/
COPY pghoard-config.py /usr/local/bin/pghoard-config
COPY pghoard-entrypoint.sh /usr/local/bin/pghoard-entrypoint
COPY pghoard-restore-db.sh /usr/local/bin/pghoard-restore-db
