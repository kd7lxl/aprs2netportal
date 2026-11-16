# aprs2netportal

`aprs2netportal` is a web application for editing the APRS Tier2 server
database. Sysops manage their server records in the portal. The data is then
used to generate DNS records for aprs2.net.

It is a Django application that runs in Docker containers together with
PostgreSQL. Installation, upgrade, backup and restore instructions are in
[deploy/README.md](deploy/README.md); the code layout and development notes
are in [AGENTS.md](AGENTS.md).
