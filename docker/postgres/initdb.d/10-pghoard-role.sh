#!/bin/sh
# Runs once, when the database cluster is first initialised.
#
# Creates the role pghoard uses to take backups over the replication protocol
# and allows it to connect from the compose network. For a cluster that was
# initialised without PGHOARD_DB_PASSWORD, see "Enabling backups on an
# existing database" in deploy/README.md.
set -e

if [ -z "$PGHOARD_DB_PASSWORD" ]; then
    echo "PGHOARD_DB_PASSWORD not set, not creating the pghoard role"
    exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
     -v password="$PGHOARD_DB_PASSWORD" <<'EOF'
CREATE ROLE pghoard WITH LOGIN REPLICATION PASSWORD :'password';
EOF

echo "host replication pghoard all scram-sha-256" >> "$PGDATA/pg_hba.conf"
