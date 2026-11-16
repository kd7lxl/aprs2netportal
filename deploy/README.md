# Running aprs2netportal

The portal runs as Docker containers, defined in `compose.yaml` at the top of
the repository:

| Service | Image | What it does |
|---|---|---|
| `web` | `t2sysop-web` (Ubuntu 26.04, Django from the Ubuntu archive) | The application, served by gunicorn on port 8000. Applies database migrations when it starts. |
| `db` | `t2sysop-postgres` (official PostgreSQL image + pghoard) | PostgreSQL. Data lives in the `pgdata` volume. |
| `pghoard` | same image as `db` | Optional. Continuous backups to AWS S3. State lives in the `pghoard` volume. |

TLS is terminated by a reverse proxy on the Docker host, which is not part of
this repository; an nginx configuration for it is in `nginx-t2sysop.conf`.

The host only needs Docker Engine with the compose plugin. Which distribution
or version it runs does not matter.

Contents: [Installation](#installation) ·
[Reverse proxy](#reverse-proxy) ·
[LoTW certificate login](#lotw-certificate-login) ·
[Migrating from the Django 1.6 server](#migrating-from-the-django-16-server) ·
[Upgrades](#upgrades) ·
[Backups](#backups) ·
[Restoring from backup](#restoring-from-backup) ·
[Development environment](#development-environment)

## Installation

    git clone https://github.com/hessu/aprs2netportal.git
    cd aprs2netportal
    cp .env.example .env
    chmod 600 .env

Edit `.env`. At least `SECRET_KEY`, `POSTGRES_PASSWORD`, `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS` must be set; every setting is described in the file.
If you are going to use backups, set `PGHOARD_DB_PASSWORD` *before* the first
start, so that the backup role is created together with the database.

    docker compose build --pull
    docker compose up -d
    docker compose ps

For a new, empty installation create an administrator:

    docker compose exec web python3 manage.py createsuperuser

Then log in to `/admin/` and create the domain `aprs2.net` and a rotate
`rotate` in it; `/APRServe2.txt` returns 404 until that rotate exists.

Useful commands:

    docker compose logs -f web          # application and access log
    docker compose exec web python3 manage.py shell
    docker compose exec db psql -U portal portal

The application listens on `127.0.0.1:8000` of the host (`WEB_BIND`). Do not
expose it to the network.

Sessions are stored in the database and expired ones are not removed
automatically. Run this from cron once a week or so:

    docker compose exec -T web python3 manage.py clearsessions

## Reverse proxy

A ready-made nginx configuration is in
[`nginx-t2sysop.conf`](nginx-t2sysop.conf), next to this file:

    cp deploy/nginx-t2sysop.conf /etc/nginx/sites-available/t2sysop.conf
    ln -s ../sites-available/t2sysop.conf /etc/nginx/sites-enabled/
    # edit the server name and certificate paths if they differ
    nginx -t && systemctl reload nginx

It terminates TLS with the Let's Encrypt certificate kept by dehydrated,
redirects plain HTTP (except ACME challenges) to HTTPS, passes requests to
the application on `127.0.0.1:8000`, and limits login and password reset
requests to 10 a minute per client address. `.env` must have
`BEHIND_TLS_PROXY=1` and the server name in `ALLOWED_HOSTS`.

If you write your own configuration instead, the proxy must pass the
original `Host` header, set `X-Forwarded-Proto`, set `X-Real-IP` to the
client address (the application's access log shows it; without it the log
has `-`), and always set the two `X-SSL-Client-*` headers described in the
next section. In nginx, keep all
`proxy_set_header` lines at the `server` level: a `location` with any
`proxy_set_header` of its own stops inheriting the others, which would
silently lose the `X-SSL-Client-*` overrides there.

The application sets the security headers itself, so the proxy should not
add its own copies: `Strict-Transport-Security` (one year, this host name
only; see `HSTS_SECONDS` in `.env.example`), a `Content-Security-Policy` that
only allows the portal's own scripts and styles, `X-Frame-Options: DENY`,
`X-Content-Type-Options` and `Referrer-Policy`.

Static files are served by the application itself (WhiteNoise, with
far-future cache headers); no `location /static` is needed.

`servers.json`, `rotates.json` and `APRServe2.txt` are available at both
`/servers.json` and `/sysop/servers.json` (and so on), as before.

## LoTW certificate login

Sysops can log in with their ARRL Logbook of The World certificate instead of
a password. nginx verifies the certificate and tells the application the
result in two request headers; the application logs in the user whose
username is the callsign in the certificate (compared case-insensitively).

A certificate never creates a user. Anyone with a licence can get a LoTW
certificate, so the user has to exist already, created by an administrator
in `/admin/` with the callsign as the username. A certificate for a callsign
without a user gets the ordinary login page. (The Django 1.6 portal did
create a user for any valid certificate; the users it created remain.)

1. In `nginx-t2sysop.conf`, uncomment the three `ssl_client_certificate`,
   `ssl_verify_client` and `ssl_verify_depth` lines.

2. `lotw-roots.pem` must contain the current LoTW root and production CA
   certificates. The bundle on the old server (`client-trust.pem`, from 2016)
   contains only certificates that have expired, the last one in June 2025,
   so it has to be replaced, not copied. Get the current ones from ARRL
   (they are also installed by TQSL) and check each with
   `openssl x509 -noout -subject -enddate`.

3. Set `LOTW_CLIENT_CERT_AUTH=1` in `.env` and `docker compose up -d`.

Security notes:

* The application believes the two headers. nginx must set both on every
  request (the `proxy_set_header` lines in the configuration file do that,
  to an empty value or `NONE` when there is no certificate), and nothing but nginx may be able to reach
  port 8000. Otherwise anyone can log in as anyone by sending the headers.
* Use `$ssl_client_s_dn`, not `$ssl_client_s_dn_legacy`. The application
  refuses the legacy format because a name in it can be made to look like a
  callsign attribute.
* Only LoTW CAs belong in `ssl_client_certificate`. The old bundle also
  trusted the "APRS2 servers CA"; certificates without a LoTW callsign
  attribute are refused by the application in any case.
* A user whose username is not their callsign cannot use a certificate
  until an administrator renames the user.
* With `ssl_verify_client optional`, a browser that offers some other
  client certificate (not issued by LoTW) gets nginx's "400 The SSL
  certificate error" page instead of the portal. The user has to pick "no
  certificate" or the right one.

## Outbound email

The portal sends password reset messages to sysops and error reports to
`ADMINS`. Without `EMAIL_HOST` in `.env` it only prints them to the container
log.

To send through a mail server on the Docker host (postfix, for example), set

    EMAIL_HOST=host.docker.internal
    DEFAULT_FROM_EMAIL=t2sysop@aprs2.net
    SERVER_EMAIL=t2sysop@aprs2.net
    ADMINS=you@example.net

`127.0.0.1` would not work: inside the container that is the container
itself. `host.docker.internal` is the host's address on Docker's default
bridge (normally 172.17.0.1), and the connection comes from the container's
address in one of Docker's private networks, not from localhost. So a mail
server that only serves 127.0.0.1 needs three changes on the host:

1. It has to listen on that address. For postfix, in `/etc/postfix/main.cf`:

       inet_interfaces = all

   (Listing `127.0.0.1, 172.17.0.1` also works, but then postfix fails to
   start at boot if it starts before Docker has created the bridge.)

2. It has to relay for the containers:

       mynetworks = 127.0.0.0/8 [::1]/128 172.16.0.0/12

   Use the exact subnet instead of 172.16.0.0/12 if you prefer; see
   `docker network inspect t2sysop_app`.

3. The firewall has to let the containers, and nobody else, connect to
   port 25, ahead of any rule that rejects:

       -A HOST-INPUT -i br-+ -s 172.16.0.0/12 -p tcp --dport 25 -j ACCEPT

   See "Host firewall" below. With `inet_interfaces = all`, check that
   port 25 is not open to the Internet unless the host is meant to receive
   mail.

Then `systemctl restart postfix`, `docker compose up -d` and send a test
message:

    docker compose exec web python3 manage.py sendtestemail you@example.net

## Host firewall

Docker maintains its own iptables chains for the containers and they are
lost if the host's rules are reloaded the usual way: `iptables-restore`
empties every chain in the tables its input names. This is a way to keep the
host's own rules in a file and apply them without disturbing Docker. It is
for a host that uses `iptables` (also the nftables-backed one) with the
`netfilter-persistent` package; Docker itself needs none of it.

What the portal needs from the host's firewall, if it filters incoming
connections at all:

* TCP ports 80 and 443 open for nginx.
* nginx must be able to connect to 127.0.0.1:8000. A firewall that rejects
  by default and accepts loopback traffic one port at a time needs a rule
  for it; without one nginx logs "connect() failed (111: Connection
  refused)" and answers 502.
* Port 8000 must not be reachable from anywhere else. Docker publishes it on
  127.0.0.1 only (`WEB_BIND`), so no rule is needed for that.
* Port 25 from the containers, if they send mail through the host; see
  "Outbound email".

The host's rules go in a chain of their own, `HOST-INPUT`. With `--noflush`,
`iptables-restore` leaves everything alone except the user-defined chains
declared in its input, which it empties and refills in one atomic step.

`/etc/iptables/rules.v4` is only a skeleton. It is loaded at boot, before
Docker starts and adds its chains:

    *filter
    :INPUT DROP [0:0]
    :FORWARD ACCEPT [0:0]
    :OUTPUT ACCEPT [0:0]
    :HOST-INPUT - [0:0]
    -A INPUT -j HOST-INPUT
    COMMIT

The rules themselves are in `/etc/iptables/host-input.v4`, in the order they
are tried. For example:

    *filter
    :HOST-INPUT - [0:0]
    -A HOST-INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
    -A HOST-INPUT -p icmp -j ACCEPT
    -A HOST-INPUT -p tcp --dport 22 -j ACCEPT
    -A HOST-INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT
    # nginx to the portal
    -A HOST-INPUT -i lo -p tcp --dport 8000 -j ACCEPT
    # the portal's containers to the mail server on the host
    -A HOST-INPUT -i br-+ -s 172.16.0.0/12 -p tcp --dport 25 -j ACCEPT
    -A HOST-INPUT -j REJECT --reject-with icmp-port-unreachable
    COMMIT

After editing the file, check it and apply it:

    iptables-restore --noflush --test /etc/iptables/host-input.v4 && \
    iptables-restore --noflush /etc/iptables/host-input.v4

To load it at boot, right after the skeleton, run
`systemctl edit netfilter-persistent` and enter:

    [Service]
    ExecStartPost=/sbin/iptables-restore --noflush /etc/iptables/host-input.v4

IPv6 works the same way, with `rules.v6`, a `host-input.v6`,
`ip6tables-restore` and a second `ExecStartPost` line. Remember that IPv6
needs ICMPv6 (`-p ipv6-icmp -j ACCEPT`) for neighbour discovery.

To move a running host to this layout without a reboot, load the chain and
put the jump first in `INPUT`. The old rules after it are no longer reached
and can be deleted one by one, or left for the next reboot to clear:

    iptables-restore --noflush /etc/iptables/host-input.v4
    iptables -I INPUT 1 -j HOST-INPUT

Things to avoid:

* Do not apply changes with `systemctl restart netfilter-persistent`,
  `netfilter-persistent reload` or a plain `iptables-restore`. They empty
  Docker's chains, and the containers lose their network until
  `systemctl restart docker`.
* Do not run `netfilter-persistent save` or `iptables-save > rules.v4`: it
  writes Docker's runtime rules into the skeleton.
* Always run the `--test` form first. If `host-input.v4` does not load at
  boot, what remains is the skeleton's `DROP` policy, and the host accepts
  no connections at all, SSH included.

## Migrating from the Django 1.6 server

Everything in this document was rehearsed in November 2026, backups and
restores against both a local S3-compatible server and AWS S3. This migration
was rehearsed
with a copy of the production database (PostgreSQL 9.3):
the three export files came out byte-identical to what the old server served.

1. On the old server, dump the database. The session table holds millions of
   expired sessions and the cache table is not used any more; leave their
   contents behind:

       sudo -u postgres pg_dump -Fc --no-owner --no-acl \
           --exclude-table-data=django_session --exclude-table-data=cache \
           portal > portal.dump

   For the real switch, stop the old application first (`service uwsgi
   stop`), so that nothing changes after the dump.

2. On the new host, with `.env` filled in, start only the database and load
   the dump into it:

       docker compose up -d db
       docker compose exec -T db pg_restore --no-owner --no-acl \
           -U portal -d portal < portal.dump

   One error, `schema "public" already exists`, is expected and harmless.

3. Bring the schema up to date. The tables already exist, so the initial
   migrations must be recorded rather than run; `--fake-initial` does that
   and then applies the changes Django has made to its own tables since 1.6:

       docker compose run --rm web python3 manage.py migrate --fake-initial

   (Starting `web` before this step fails safely with `relation
   "django_content_type" already exists` and changes nothing.)

4. Remove what the old stack left behind:

       docker compose exec -T db psql -U portal portal <<'EOF'
       DROP TABLE south_migrationhistory;
       DROP TABLE cache;
       DROP INDEX sysop_rotate_dns_name_like;
       DROP INDEX sysop_server_dns_name_like;
       EOF
       docker compose run --rm web python3 manage.py remove_stale_contenttypes \
           --include-stale-apps --noinput

   The last command removes the admin's records of models that no longer
   exist (South's), together with their permissions.

5. `docker compose up -d`, then compare the exports with the old server. The
   application only answers to the names in `ALLOWED_HOSTS`, so a request
   straight to port 8000 has to say which host it is for:

       for f in servers.json rotates.json APRServe2.txt; do
           curl -s -H 'Host: t2sysop.aprs2.net' http://127.0.0.1:8000/$f |
               cmp - <(curl -s https://t2sysop.aprs2.net/$f) && echo "$f identical"
       done

6. Point the reverse proxy (or DNS) at the new installation.

Things that change for users:

* Everyone has to log in again (sessions are not carried over, and the
  secret key is new).
* Eight accounts that have not logged in since 2014 have passwords in a
  format (unsalted MD5) that Django no longer accepts. They cannot log in
  with the old password; "Reset Password" or a LoTW certificate works.
* Logging out is a button, not a link.
* A LoTW certificate no longer creates an account. It logs in an existing
  user whose username is the certificate's callsign, and nothing else.

Other things on the old server that the portal's files were shared with: the
Graphite vhost (`graph.conf`) includes `/var/www/aprs2netportal/deploy/uwsgi_params`,
so it breaks if that directory is removed before Graphite is dealt with.

## Upgrades

Take note of the running versions first: `docker compose images`.

### The application

    git pull
    docker compose build web
    docker compose up -d web

Database migrations are applied when the container starts. To go back, check
out the previous commit and repeat; if the newer version had migrated the
database, restore the database too (migrations are not reversed
automatically).

### Operating system packages, Django and Python security updates

The `web` image is Ubuntu 26.04 with Django, psycopg, gunicorn and WhiteNoise
installed from the Ubuntu archive, so they are updated by rebuilding on top of
a current base image:

    docker compose build --pull --no-cache web
    docker compose up -d web

Do this regularly (monthly, and when a Django security release is announced).
Ubuntu 26.04 ships Django 5.2 LTS and updates stay within 5.2, so no code
changes are expected.

Moving to a newer Ubuntu release is a code change: edit the `FROM` line in
`Dockerfile`, rebuild, and run the tests (see AGENTS.md) with
`-W error::DeprecationWarning`, which turns everything the next Django
version will remove into a failure.

### PostgreSQL minor versions (18.x to 18.y)

Minor versions are compatible on disk. Rebuild on a current base image and
restart; this takes the database down for a few seconds:

    docker compose build --pull --no-cache db
    docker compose up -d

The `pghoard` service uses the same image and is restarted along with it.

### PostgreSQL major versions (18 to 19, ...)

A major version cannot read the previous version's data directory, and the
pghoard backups (which are copies of the data directory) cannot be restored
into a different major version either. The database is small, so the upgrade
is a dump and a reload, a few minutes of downtime. Each major version keeps
its data in its own directory of the `pgdata` volume
(`/var/lib/postgresql/<major>/docker`), so the old data stays untouched until
you remove it.

1. Check that pghoard supports the new version (`SUPPORTED_VERSIONS` in its
   `pghoard/config.py`) and update `PGHOARD_VERSION` in
   `docker/postgres/Dockerfile` if needed.

2. Stop the application and dump everything, roles included:

       docker compose stop web pghoard
       docker compose exec -T db pg_dumpall -U portal > upgrade.sql

3. Stop the old server, switch versions, and start the new one, which
   initialises an empty cluster in its own directory:

       docker compose stop db
       # in .env: POSTGRES_VERSION=19, and a new PGHOARD_SITE, e.g. t2sysop-pg19
       docker compose build --pull db
       docker compose up -d db

4. Load the dump. The errors `role "portal" already exists`, `database
   "portal" already exists` and, if backups are enabled, `role "pghoard"
   already exists` are expected; there should be no others:

       docker compose exec -T db psql -U portal -d postgres < upgrade.sql 2>&1 | grep ERROR

   If backups are enabled, also repeat the `pg_hba.conf` step of "Enabling
   backups on an existing database" below; the new cluster only gets that
   line by itself when `PGHOARD_DB_PASSWORD` was set as it was initialised.

5. Start everything and check the portal:

       docker compose up -d

   pghoard takes a new base backup under the new site name right away.

6. When satisfied, remove the old data directory, and later the old backup
   site from the bucket:

       docker compose exec -u root db rm -rf /var/lib/postgresql/18

To go back before step 6: stop everything, set `POSTGRES_VERSION` and
`PGHOARD_SITE` back, rebuild `db`, and start. The old directory is as it was
when the old server was stopped.

### pghoard

Change `PGHOARD_VERSION` in `docker/postgres/Dockerfile` to the new release
tag or commit, then rebuild and restart as for a PostgreSQL minor version.
Afterwards check `docker compose logs pghoard` for upload errors and that
`list-basebackups` (below) works.

## Backups

[pghoard](https://github.com/Aiven-Open/pghoard) keeps a continuous physical
backup in an S3 bucket: a full base backup every 24 hours, plus the
write-ahead log (WAL) streamed from the server as it is written. From these
the database can be restored to any moment between the oldest base backup
kept (14 by default) and a few minutes ago.

How recent "a few minutes ago" is: WAL is uploaded one complete segment at a
time, and the database is told to finish the current segment every 10 minutes
if anything changed (`POSTGRES_ARCHIVE_TIMEOUT`, seconds). So at most the
last 10 minutes of changes exist only on the host.

If pghoard is stopped or cannot reach S3, the database keeps the WAL it has
not received yet, up to `POSTGRES_WAL_KEEP_SIZE` (4 GB, which is 256
segments: at least 42 hours of constant changes, normally weeks), and
pghoard catches up when it is back. After a longer outage than that the
archive has a gap: pghoard logs `requested WAL segment ... has already been
removed`, and a point-in-time restore cannot cross the gap. Fix it by
switching to a new `PGHOARD_SITE` name, which starts over with a fresh base
backup; restores to times before the gap still work from the old site.

### Setting up

1. Create a private S3 bucket (block all public access; versioning is not
   needed) and an IAM user whose only permissions are:

       {
         "Version": "2012-10-17",
         "Statement": [
           {"Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": "arn:aws:s3:::BUCKET"},
           {"Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject",
                       "s3:AbortMultipartUpload"],
            "Resource": "arn:aws:s3:::BUCKET/*"}
         ]
       }

   Mind the two different resources: the object actions only match the
   `/*` form. With it missing, pghoard starts and lists backups without
   complaint but every upload fails with `AccessDenied ... s3:PutObject`.

2. In `.env` set `COMPOSE_PROFILES=backup`, `PGHOARD_DB_PASSWORD` and the
   `PGHOARD_S3_*` settings.

3. Optional but recommended: encrypt the backups before they leave the host.
   Generate an RSA key pair:

       mkdir -p keys
       openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out keys/private.pem
       openssl pkey -in keys/private.pem -pubout -out keys/public.pem

   Set `PGHOARD_ENCRYPTION_KEY_ID=key1` in `.env`. Then **move
   `keys/private.pem` off the server** to somewhere safe (a password
   manager): backing up only needs `public.pem`, and a backup that can be
   decrypted with a key stored next to the S3 credentials is not much
   protected. Without `private.pem` the backups cannot be restored at all,
   so keep more than one copy.

4. Start it:

       docker compose up -d
       docker compose logs -f pghoard

   The first base backup is taken immediately.

### Enabling backups on an existing database

The `pghoard` database role is created only when the database is first
initialised with `PGHOARD_DB_PASSWORD` set. If the database already existed
(for example, backups were not configured at installation), create the role
and allow it to connect by hand, once:

    docker compose exec -T db psql -U portal -d postgres \
        -c "CREATE ROLE pghoard WITH LOGIN REPLICATION PASSWORD 'the PGHOARD_DB_PASSWORD value'"
    docker compose exec -T db sh -c \
        'echo "host replication pghoard all scram-sha-256" >> "$PGDATA/pg_hba.conf"'
    docker compose exec -T db psql -U portal -d postgres -c "SELECT pg_reload_conf()"

A database restored from a pghoard backup already has both.

### Checking the backups

    docker compose exec pghoard sh -c \
        'pghoard_restore list-basebackups --config $PGHOARD_CONFIG --site $PGHOARD_SITE'
    docker compose logs --since 24h pghoard | grep -E 'WARNING|ERROR'

There should be a base backup from the last 24 hours. pghoard also creates
alert files in the `pghoard` volume when something keeps failing:

    docker compose exec pghoard ls /var/lib/pghoard/spool

Any file there named `*_warning` or `*_alert` means trouble, and the log says
what. A backup that has never been restored is a hope, not a backup: run the
restore procedure against a scratch copy of this directory on another machine
once in a while.

A logical dump is a useful second line of defence, restorable to any
PostgreSQL version, and small enough to keep anywhere:

    docker compose exec -T db pg_dump -Fc -U portal portal > portal-$(date +%F).dump

## Restoring from backup

This replaces the database with a copy from S3. It works the same on the
original host and on a brand new one (clone the repository and recreate
`.env` with the same `SECRET_KEY`, `PGHOARD_*` and `POSTGRES_*` settings
first; `PGHOARD_SITE` and `POSTGRES_VERSION` must be what they were when the
backup was taken).

1. Stop everything:

       docker compose stop

2. If the backups are encrypted, put `private.pem` back into the `keys`
   directory for the duration of the restore.

3. Fetch the latest base backup into the data directory. This **deletes the
   current data directory** of this PostgreSQL version:

       docker compose run --rm --no-deps pghoard pghoard-restore-db

   To go back to an earlier moment instead of the latest state, add a target
   time (UTC):

       docker compose run --rm --no-deps pghoard pghoard-restore-db \
           --recovery-target-time 2026-11-15T12:00:00+00:00

   If this step fails, do **not** start `db`: it would find an empty data
   directory and create a new, empty database in it. Fix the problem and
   repeat the step.

4. Start pghoard, then the database. The database fetches the WAL it needs
   from S3 through pghoard and replays it:

       docker compose up -d --no-deps pghoard
       docker compose up -d db
       docker compose logs -f db

   Wait for `archive recovery complete` and `database system is ready to
   accept connections`. Messages about `.history` files and the next WAL
   segment "not found from archive" on the way are normal: that is how the
   server finds the end of the backup.

   When a target time was given, the server stops there and waits, read-only,
   so that you can check that this is the moment you wanted. To accept it:

       docker compose exec db psql -U portal -d postgres -c "SELECT pg_wal_replay_resume()"

5. Check the data, then start the application:

       docker compose exec db psql -U portal portal -c "SELECT count(*) FROM sysop_server"
       docker compose up -d

6. Remove `private.pem` from the server again, and restart pghoard:

       rm keys/private.pem
       docker compose restart pghoard

   The restart matters: pghoard's configuration file in the `pghoard` volume
   is written when the container starts and holds a copy of the key. Until
   it is rewritten without it, the key is still on the server, next to the
   S3 credentials.

7. After restoring to a target time, change `PGHOARD_SITE` in `.env` to a new
   name and `docker compose up -d`. **Until you do, nothing is being backed
   up**: the restored database has a different history than the later WAL
   already in the bucket under the old name, and pghoard keeps failing with
   `requested starting point ... is ahead of the WAL flush position`. Under
   the new name it takes a fresh base backup at once; check with
   `list-basebackups`. Delete the old site from the bucket when it is no
   longer needed. After a restore to the latest state this is not required.

## Development environment

To try the whole thing locally:

    cp .env.example .env    # set SECRET_KEY, POSTGRES_PASSWORD, ALLOWED_HOSTS=localhost,
                            # BEHIND_TLS_PROXY=0, DEBUG=1
    docker compose up -d --build
    docker compose exec web python3 manage.py createsuperuser

and browse to http://127.0.0.1:8000/. Tests do not need the database
container; see AGENTS.md.

### Docker inside an LXD container

If Docker should not run directly on the workstation, it can run in an
unprivileged LXD container. What it took on an Ubuntu 22.04 host (kernel
5.15, LXD 4.0):

    lxc launch ubuntu:26.04 t2sysop-docker -c security.nesting=true
    lxc config device add t2sysop-docker src disk \
        source=/path/to/aprs2netportal path=/src readonly=true
    lxc exec t2sysop-docker -- apt-get install -y docker.io docker-compose-v2 \
        docker-buildx crun fuse-overlayfs

and `/etc/docker/daemon.json` in the container:

    {
      "features": { "containerd-snapshotter": false },
      "storage-driver": "fuse-overlayfs",
      "default-runtime": "crun",
      "runtimes": { "crun": { "path": "/usr/bin/crun" } }
    }

* `crun`: runc refuses to start containers under LXD's AppArmor profile
  (`open sysctl net.ipv4.ip_unprivileged_port_start file: reopen fd 8:
  permission denied`).
* `fuse-overlayfs`: on this kernel the kernel's overlayfs cannot be mounted
  on LXD's idmapped root filesystem (`failed to mount ... overlay ... invalid
  argument`). Do not use the `native`/`vfs` drivers as a workaround: they
  copy every image layer in full and fill the disk in a few builds. A host
  with kernel 5.19 or newer should not need either setting.

The repository is mounted read-only, so keep the environment file in the
container and pass it explicitly:

    lxc exec t2sysop-docker -- sh -c \
        'cd /src && docker compose --env-file /root/t2sysop.env up -d --build'

If the LXD container is bridged to a public network, published ports are
reachable from there: keep `WEB_BIND` on 127.0.0.1.
