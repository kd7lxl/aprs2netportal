#!/bin/sh
# Restore the database cluster from the pghoard backups in object storage.
# Run in a one-off pghoard container that has the database volume mounted;
# see "Restoring from backup" in deploy/README.md.
#
# Extra arguments go to "pghoard_restore get-basebackup", for example
#   --recovery-target-time 2026-11-15T12:00:00+00:00
set -e

target="/var/lib/postgresql/${PG_MAJOR}/docker"

if [ -e "$target/postmaster.pid" ]; then
    echo "$target looks like a running database, stop the db service first" >&2
    exit 1
fi

if [ "$(id -u)" != "0" ]; then
    echo "run this as root: docker compose run --rm --no-deps pghoard pghoard-restore-db" >&2
    exit 1
fi

# pghoard_restore replaces the data directory, so the postgres user needs to
# be able to write to its parent.
mkdir -p "$target"
chown postgres:postgres "$(dirname "$target")" "$target"
chmod 0700 "$target"

if ! gosu postgres pghoard_restore get-basebackup \
        --config "$PGHOARD_CONFIG" \
        --site "${PGHOARD_SITE:-t2sysop}" \
        --target-dir "$target" \
        --overwrite \
        --restore-to-primary \
        "$@"; then
    echo >&2
    echo "RESTORE FAILED. The data directory may now be empty or incomplete." >&2
    echo "Do NOT start the db service: it would initialise a new, empty database." >&2
    exit 1
fi

# The database server fetches WAL from the pghoard service while recovering.
# pghoard writes a restore_command that expects pghoard on localhost; point
# it at the pghoard container instead.
sed -i 's/--mode restore --port /--mode restore --host pghoard --port /' \
    "$target/postgresql.auto.conf"
grep -q -- '--host pghoard' "$target/postgresql.auto.conf" || {
    echo "could not adjust restore_command in postgresql.auto.conf" >&2
    exit 1
}

# Ask for archive recovery: without this file PostgreSQL 12+ ignores
# restore_command and would not replay the archived WAL. (pghoard_restore
# only creates a signal file when restoring a standby.)
gosu postgres touch "$target/recovery.signal"

echo "Base backup restored to $target. Start the pghoard and db services to replay WAL."
