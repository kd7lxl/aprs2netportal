#!/usr/bin/env python3
"""Write a pghoard configuration file built from environment variables."""
import json
import os
import sys


def require(name):
    value = os.environ.get(name)
    if not value:
        sys.exit("pghoard-config: environment variable %s is required" % name)
    return value


def main():
    target = sys.argv[1]
    pg_major = require('PG_MAJOR')
    site = os.environ.get('PGHOARD_SITE') or 't2sysop'

    storage_type = os.environ.get('PGHOARD_STORAGE_TYPE') or 's3'
    if storage_type == 's3':
        storage = {
            'storage_type': 's3',
            'bucket_name': require('PGHOARD_S3_BUCKET'),
            'region': require('PGHOARD_S3_REGION'),
            'aws_access_key_id': require('PGHOARD_S3_ACCESS_KEY_ID'),
            'aws_secret_access_key': require('PGHOARD_S3_SECRET_ACCESS_KEY'),
        }
        if os.environ.get('PGHOARD_S3_PREFIX'):
            storage['prefix'] = os.environ['PGHOARD_S3_PREFIX']
        # S3-compatible services (testing with MinIO etc.)
        if os.environ.get('PGHOARD_S3_HOST'):
            storage['host'] = os.environ['PGHOARD_S3_HOST']
            storage['port'] = int(os.environ.get('PGHOARD_S3_PORT') or 9000)
            storage['is_secure'] = os.environ.get('PGHOARD_S3_SECURE', '0') == '1'
    elif storage_type == 'local':
        storage = {
            'storage_type': 'local',
            'directory': require('PGHOARD_LOCAL_DIRECTORY'),
        }
    else:
        sys.exit("pghoard-config: unsupported PGHOARD_STORAGE_TYPE %r" % storage_type)

    site_config = {
        'active': True,
        'active_backup_mode': 'pg_receivexlog',
        'basebackup_mode': 'pipe',
        'basebackup_interval_hours': int(os.environ.get('PGHOARD_BASEBACKUP_INTERVAL_HOURS') or 24),
        'basebackup_count': int(os.environ.get('PGHOARD_BASEBACKUP_COUNT') or 14),
        'nodes': [{
            'host': os.environ.get('POSTGRES_HOST') or 'db',
            'port': int(os.environ.get('POSTGRES_PORT') or 5432),
            'user': 'pghoard',
            'password': require('PGHOARD_DB_PASSWORD'),
        }],
        'pg_bin_directory': '/usr/lib/postgresql/%s/bin' % pg_major,
        # Backups are taken over the network, but pghoard reads the server
        # version from here, and writes WAL files here when the database
        # asks for them during a restore.
        'pg_data_directory': '/var/lib/postgresql/%s/docker' % pg_major,
        'object_storage': storage,
    }

    # Optional client-side encryption of everything sent to object storage.
    key_id = os.environ.get('PGHOARD_ENCRYPTION_KEY_ID')
    if key_id:
        with open(require('PGHOARD_ENCRYPTION_PUBLIC_KEY_FILE')) as f:
            keys = {'public': f.read()}
        # The private key is needed only for restoring. Keep it off the
        # server in normal operation and provide it when restoring.
        private_key_file = os.environ.get('PGHOARD_ENCRYPTION_PRIVATE_KEY_FILE')
        if private_key_file and os.path.exists(private_key_file):
            with open(private_key_file) as f:
                keys['private'] = f.read()
        site_config['encryption_key_id'] = key_id
        site_config['encryption_keys'] = {key_id: keys}

    config = {
        'backup_location': '/var/lib/pghoard/spool',
        'json_state_file_path': '/var/lib/pghoard/pghoard_state.json',
        # Reachable from the db container, which fetches WAL through this
        # API during a restore. Not published outside the compose network.
        'http_address': '0.0.0.0',
        'http_port': 16000,
        'log_level': os.environ.get('PGHOARD_LOG_LEVEL') or 'INFO',
        'backup_sites': {site: site_config},
    }

    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
