#!/bin/sh
# Entrypoint of the pghoard backup container. Starts as root.
#
#   (no arguments)   run the pghoard backup daemon, as the postgres user
#   anything else    run it, as root, with PGHOARD_CONFIG pointing at the
#                    generated configuration, e.g. pghoard-restore-db
set -e

export PGHOARD_CONFIG="${PGHOARD_CONFIG:-/var/lib/pghoard/pghoard.json}"
mkdir -p /var/lib/pghoard/spool
# Run as root so that the encryption key files can be read whatever their
# ownership on the host; the keys end up in the configuration file, which
# only the postgres user can read.
pghoard-config "$PGHOARD_CONFIG"
chown -R postgres:postgres /var/lib/pghoard

if [ "$#" -eq 0 ]; then
    # pghoard keeps a progress file in its working directory.
    cd /var/lib/pghoard
    exec gosu postgres pghoard --config "$PGHOARD_CONFIG"
fi

exec "$@"
