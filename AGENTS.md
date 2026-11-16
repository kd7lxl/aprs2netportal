# AGENTS.md

Guidance for coding agents (and humans) working on this repository.

## What this is

`aprs2netportal` is the sysop portal for the APRS-IS Tier2 network (aprs2.net).
Server operators log in and maintain the records of their servers; admins
manage domains, rotates (DNS round-robin groups) and reserved hostnames through
the Django admin. The portal's machine-readable outputs are consumed by
external systems that generate the aprs2.net DNS zone and monitor the network:

| URL | View | Consumer-facing contract |
|---|---|---|
| `/servers.json` (also `/sysop/servers.json`) | `sysop.views.servers_json` | dict keyed by `server_id`; includes sysop email only for authenticated requests and only when `email_alerts` is on |
| `/rotates.json` | `sysop.views.rotates_json` | dict keyed by rotate FQDN, each with nested `servers` dict |
| `/APRServe2.txt` | `sysop.views.server_list` | legacy text server list for APRS client software; requires a rotate `rotate.aprs2.net` to exist |

**Treat the shape of these three outputs as a stable external API.** Do not
change keys, nesting or text layout without being asked to.

## Stack

- Python 3 / Django 5.2 LTS, using the versions packaged in Ubuntu 26.04
  (`python3-django`, `python3-psycopg`, `gunicorn`, `python3-whitenoise`).
  There is deliberately no `requirements.txt`: the dependency list is the
  `apt-get install` line in `Dockerfile`.
- PostgreSQL 18 in production (compose service `db`); SQLite when
  `POSTGRES_HOST` is unset, which is what the test suite uses.
- Runs as Docker containers defined in `compose.yaml`: `web` (gunicorn, static
  files served by WhiteNoise), `db`, and optionally `pghoard` (continuous
  backups to S3). TLS, and LoTW client certificate verification, are done by a
  reverse proxy outside this repository.
- All configuration comes from environment variables (`.env`, see
  `.env.example`); `settings.py` has no deployment-specific values.
- Bootstrap 5.3 vendored in `assets/vendor/`; no jQuery, no CDN, no inline
  scripts or styles. A strict Content-Security-Policy (`settings.py`, sent by
  `utils/middleware.py`) enforces that in the browser and tests check the
  templates, including the admin's. Do not add `'unsafe-inline'` or
  third-party hosts to the policy; put scripts and styles in `assets/`.
- GitHub Actions (`.github/workflows/test.yml`) builds both images and runs
  the tests, the migration check and `check --deploy` on every push.

The code was written in 2014 for Python 2.7 / Django 1.6 / South and ported in
2026. The pre-port code is at commit `e74f998` if behaviour needs comparing.

## Layout

```
manage.py                    Django entry point
compose.yaml                 web + db + pghoard services
Dockerfile                   Application image (ubuntu:26.04 + apt packages)
.env.example                 Every supported environment variable, documented
aprs2netportal/              Project package
  settings.py                Environment-driven settings
  urls.py                    Root URLconf: admin, auth/password views;
                             includes sysop.urls at /sysop/ (canonical, what
                             reverse() returns) and again at / (namespace
                             "root", kept for external consumers)
  wsgi.py                    WSGI entry point
sysop/                       The one real application
  models.py                  Domain, Server, Rotate, ReservedHostname and the
                             signal handlers that clear the export cache
  views.py                   JSON/text exports + login-required HTML views
  forms.py                   SysopServerForm (locks admin-only fields), UserForm
  admin.py                   Admin registrations; Rotate<->Server inline
  urls.py                    App URLconf (named URLs)
  countries.py               ISO 3166 code -> name dict used as choices
  templatetags/sysop.py      {% servertable %} inclusion tag
  templates/sysop/           index, edit_server, servertable, APRServe2.txt
  migrations/0001_initial.py Matches the schema the South migrations produced
  tests.py                   Exports, permissions, accounts, admin, frontend
lotwauth/                    LoTW client certificate login (no models)
  dn.py                      Subject DN parsing, callsign extraction
  backends.py                Authentication backend (username = callsign)
  middleware.py              Logs in from headers set by the reverse proxy
  tests.py
utils/                       Template helpers and middleware (no models)
  middleware.py              Content-Security-Policy header
  templatetags/bootstrap.py  bs_widget, is_checkbox, alert_class filters
  templatetags/navigation.py {% active %} tag for nav highlighting
templates/                   Project-level templates
  base.html, base_narrow.html  Page layouts (sidebar / centered card)
  includes/                  Shared form field, errors, messages partials
  registration/              Login, password change/reset, profile
  403.html, 404.html, 500.html
assets/                      Static sources: portal.css, portal.js, favicon,
                             vendor/bootstrap (collected to ./staticfiles)
docker/
  entrypoint.sh              web container: migrate, then gunicorn
  healthcheck.py             web container health probe (sends an allowed
                             Host header)
  postgres/                  db + pghoard image (official postgres + pghoard),
                             backup role init script, config generator,
                             restore helper
deploy/README.md             Installation, reverse proxy, migration from the
                             legacy server, upgrades, backup and restore
deploy/nginx-t2sysop.conf    nginx reverse proxy configuration for the host
```

## Building and testing

Nothing runs directly on the developer host: dependencies exist only in the
image. Build it and run the tests in it:

    docker build -t t2sysop-web .
    docker run --rm -e SECRET_KEY=x t2sysop-web \
        python3 -W error::DeprecationWarning manage.py test

The build runs `collectstatic` with the manifest storage, so a broken static
reference fails the build. Run the tests before every commit. After changing
models, generate migrations inside the image (`manage.py makemigrations`) and
copy the file out; `manage.py makemigrations --check` must report no changes.

On the maintainer's workstation Docker runs inside the LXD container
`t2sysop-docker` (the repository is mounted read-only at `/src`), so prefix
the commands: `lxc exec t2sysop-docker -- sh -c 'cd /src && ...'`. That
container has a public IP address: never publish container ports there other
than on 127.0.0.1. See "Development environment" in `deploy/README.md`.

## Data model

- **Domain** — a DNS domain (`aprs2.net`, `aprs.net`, `firenet.us`).
- **Server** — a Tier2 server or hub. `hostname` + `domain` form the FQDN;
  `server_id` is the APRS-IS server ID (e.g. `T2FINLAND`) and is the key in
  `servers.json`. Has `owner` (FK to `auth.User`) and `authorized_sysops`
  (M2M to `auth.User`), IPv4/IPv6 addresses, location, descriptive fields and
  the flags `deleted`, `out_of_service` and `email_alerts`.
- **Rotate** — a round-robin DNS name with an `eligible` M2M to Server.
  `regional` marks the primary regional rotates listed in `APRServe2.txt`.
- **ReservedHostname** — hostnames that may not be used for servers or rotates.

`Server.clean()` and `Rotate.clean()` enforce that a hostname is not reserved
and that servers and rotates do not share a name. Users are stock
`django.contrib.auth` users; there is no profile model.

## Behaviour worth knowing

- **Permissions:** any logged-in user can view any server record. Only the
  owner or an authorized sysop can save it (`sysop.views.server_detail`).
  `server_id`, `hostname` and `domain` are locked for sysops by
  `SysopServerForm` (the form fields are `disabled`, so submitted values
  for them are ignored); those fields are changed through the admin only. Note that a
  sysop *can* change `owner`, `deleted` and `authorized_sysops`.
- **Caching:** the three export views are cached for 30 minutes with
  `cache_page` and sent with no-cache headers to clients. Signal handlers in
  `sysop/models.py` clear the whole cache when a Server, Rotate, Domain,
  rotate membership or a user's email changes. In the container the cache is
  file based (`CACHE_DIR`) so that all gunicorn workers share it.
- **`servers.json` varies by authentication**: authenticated requests get a
  separate cache entry (key prefix) because they include sysop emails.
- **`APRServe2.txt` is served with CRLF line endings** and without HTML
  escaping. Django's template loader normalises line endings, so the view
  re-adds them; the template file itself is also CRLF. Edit it with care.
- **LoTW login** (`LOTW_CLIENT_CERT_AUTH`): the proxy verifies the client
  certificate and passes `X-SSL-Client-Verify` and `X-SSL-Client-S-DN`. The
  callsign in the DN is matched case-insensitively against usernames.
  **A certificate must never create a user**: anyone with a licence can get
  one, and the maintainer does not want that to be enough for access. Do not
  add auto-creation back, not even as an option. The headers are trusted
  blindly, so the application port must only be reachable through the
  proxy. Only RFC 4514 DNs are accepted; the legacy slash-separated form is
  refused because it can be spoofed through the certificate holder's name.
- Logging out is a POST (Django 5); there is no GET logout link.
- Soft delete: `deleted` servers stay in `servers.json` (flagged) but are
  excluded from the HTML lists and `APRServe2.txt`.

## Known rough edges

- A sysop can change `owner`, `deleted` and `authorized_sysops` of their own
  server, and so can lock themselves out or "delete" the record. This is
  long-standing behaviour, kept as is.
- Every page is reachable under both `/sysop/...` and `/...`.
- `Server.country` stores the ISO code and `APRServe2.txt` prints the code,
  not the country name.
- There is no uniqueness constraint on `server_id` or on hostname + domain;
  `servers.json` is keyed by `server_id`, so duplicates silently collapse.

## Conventions

- Do not add `Co-Authored-By` (or any other AI attribution) trailers to commits.
- Commit messages: short imperative sentence ending with a period, matching
  the existing history (`Add form errors to login page.`).
- 4-space indentation, PEP 8-ish Python; Django templates indented with spaces.
- Keep it a small, boring Django project: prefer stock Django features over
  new dependencies.
