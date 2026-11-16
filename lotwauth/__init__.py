"""
Login with ARRL Logbook of The World (LoTW) TLS client certificates.

The application never sees the TLS session. The reverse proxy in front of it
requests a client certificate, verifies it against the LoTW CA chain and
passes the outcome in two request headers:

    X-SSL-Client-Verify: SUCCESS            (nginx: $ssl_client_verify)
    X-SSL-Client-S-DN:   <subject DN>       (nginx: $ssl_client_s_dn)

The proxy MUST set both headers on every request, also to an empty value when
no certificate was presented; otherwise anyone can log in as any callsign by
sending the headers themselves. For the same reason the application port must
not be reachable except through the proxy.

The callsign in the certificate subject (OID 1.3.6.1.4.1.12348.1.1) is
matched against the usernames of existing users. A certificate never creates
a user: anyone with a licence can get one, and that must not be enough to get
into the portal. Enabled with the LOTW_CLIENT_CERT_AUTH setting.

This replaces the django_ssl_auth package (HamWAN/django-ssl-client-auth)
that the portal used with Django 1.6, which did create users.
"""
