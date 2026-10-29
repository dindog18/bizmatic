# Docker deployment on Ubuntu

The stack runs Django with Gunicorn, PostgreSQL 17, and an unprivileged Nginx
proxy. Database data, uploaded originals, the database-credential encryption key,
and collected static files use separate named volumes. Only Nginx publishes a
host port. Django runs as UID/GID 10001; migrations and static collection run
before Gunicorn starts. The proxy waits for application readiness. The app has
a default 2 GiB memory limit, two-CPU quota and 256-process limit; tune
APP_MEMORY_LIMIT and APP_CPUS for the server. These contain worker resource use
but do not turn native parser failures into successful extractions.

## First installation

1. Install Docker Engine and the Compose plugin using the [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/).
   Use Compose 2.30 or newer; the runtime environment file uses `format: raw`.
   Check `docker version` and `docker compose version`. Commands below assume
   your account can use Docker; otherwise prefix the wrapper with `sudo`.
2. Check out this repository and run the following from its root:

   ```sh
   python3 deploy/configure.py --host 192.168.0.175 --port 8005
   ```

   Replace the example IP with your Ubuntu server's IP or DNS name. This creates
   an ignored `.env.docker` with random Django/database secrets and permissions
   0600. It refuses to overwrite an existing file. Keep that file for upgrades;
   do not regenerate database passwords or the Django secret on every restart.
3. Review `.env.docker`. To allow the intended trusted LAN to reach the server,
   change `BIZMATIC_BIND_ADDRESS=127.0.0.1` to the server's actual LAN IP, such as
   `192.168.0.175`. The generator adds the host and port to Django's allowed hosts
   and CSRF origins but deliberately leaves the listener on loopback initially.
   Configure the LLM provider, model and endpoint before extraction. See below.
4. Build and start:

   ```sh
   ./deploy/compose up -d --build --wait --wait-timeout 180
   ./deploy/compose ps
   python3 deploy/smoke.py --base-url http://192.168.0.175:8005
   ```

   The first build downloads Python wheels and base images. On slow hardware,
   increase `--wait-timeout`. Open `http://192.168.0.175:8005/documents/`.
   For localhost-only installation, leave the binding unchanged and use localhost
   in the smoke command. A fresh installation has no business data.

`deploy/compose` always supplies `.env.docker`, the correct project directory and
Compose file. Running plain `docker compose` without `--env-file .env.docker`
will not load this deployment's variables. `BIZMATIC_ENV_FILE` can select an
alternate environment file. Never print `compose config` output into a public
issue: it contains resolved secrets; use `./deploy/compose config --quiet`.

The business workspace has no application login or tenant isolation. Use a
trusted LAN/VPN or an authenticated HTTPS reverse proxy. Docker-published ports
can bypass UFW rules; use a specific bind address and appropriate upstream or
DOCKER-USER filtering rather than relying on UFW alone. See the [Docker firewall notes](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations).

## LLM connections

All existing provider variables still work. Add API keys, model names and base
URL overrides from `bizmatic_django/.env.example` to `.env.docker`; values in the
runtime file are literal and should not be surrounded by shell quotes. Module
credentials and base URLs can fall back to DOC_EXTRACTION settings, while model
names remain independent. Restart with `./deploy/compose up -d` after edits.
The image excludes the developer's `bizmatic_django/.env` and local databases.

For Ollama already running on the Ubuntu host, the default endpoint is
`http://host.docker.internal:11434`. Compose adds Linux's host-gateway mapping.
Ollama must listen on an address reachable from the Docker bridge; its default
host loopback-only listener is not reachable from a container. Configure the
host listener/network restriction deliberately, or use the internal service:

1. Set `DOC_EXTRACTION_OLLAMA_BASE_URL=http://ollama:11434` in `.env.docker`.
2. Run `./deploy/compose --profile ollama up -d`.
3. Download a model you have selected for your hardware:

   ```sh
   ./deploy/compose --profile ollama exec ollama ollama pull YOUR_MODEL
   ```

4. Set each selected `*_OLLAMA_MODEL` to that exact model name, then recreate app:
   `./deploy/compose up -d app proxy`.

The optional service does not publish Ollama to the LAN and keeps model files
in its own volume. No models are downloaded automatically. It runs on CPU by
default; GPU drivers/runtime and hardware-specific Compose overrides are an
operator choice. An Apple MLX model cannot be assumed to work on Ubuntu.
Cloud providers require no Ollama service. Models and external source databases
are not bundled into the application image.

## Existing database, originals and credential key

Docker startup creates tables in the new application database; it does not import
your existing Ubuntu/SQLite database or originals. Back up the existing database,
original files, original credential key and runtime settings before moving them.
Keep the old application stopped during final backup and cutover.

A source database profile pointing at localhost must also be updated: inside app,
localhost refers to the container. Use a reachable source host/IP or
host.docker.internal for a host service, with the source server's appropriate
listener, pg_hba, firewall and TLS settings. Connection identity changes require
password re-entry in the existing UI; Docker does not rewrite saved profiles.

For an existing PostgreSQL installation, use a PostgreSQL backup/restore into the
Compose database. For SQLite, plan a validated data migration separately: generic
`dumpdata` is intentionally blocked for encrypted source-password fields and is
not a credential migration mechanism. Do not point the new deployment at an empty
database and assume its old records have been copied.

Original-file records retain their saved `storage_path`. New Docker uploads use
`/var/lib/bizmatic/uploads`. Existing absolute paths must be preserved by a
read-only bind mount at the same container path, or remapped after verifying
all originals. For example, a private `compose.override.yaml` can mount a copied
legacy upload directory and a source database CA file:

```yaml
services:
  app:
    volumes:
      - /srv/bizmatic-legacy-uploads:/original/absolute/storage/path:ro
      - /srv/bizmatic-certs:/run/bizmatic-certs:ro
```

The wrapper uses an explicit Compose file, so include this override explicitly:
`./deploy/compose -f compose.yaml -f compose.override.yaml up -d`.
For relative legacy paths, the base directory inside the container is `/app`;
preserve the complete batch/UUID filename hierarchy. Do not expose upload or key
volumes through Nginx static-file serving.

Restore the original `db-extraction.key` **before starting app with its existing
database**. It must be owned by UID/GID 10001 with mode 0600, at
`/var/lib/bizmatic/keys/db-extraction.key` in the key volume. An administrative
one-off container can install a trusted backup from stdin without printing it:

```sh
./deploy/compose run --rm --no-deps -T app python -c 'import os,sys; p="/var/lib/bizmatic/keys/db-extraction.key"; fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.fdopen(fd,"wb").write(sys.stdin.buffer.read())' < /secure/backup/db-extraction.key
```

This refuses to overwrite any existing key. Restore into the intended empty key
volume. Wrong ownership on a previously created volume needs an explicit
administrative ownership repair; do not use world-readable permissions.
Startup verifies all saved source passwords can decrypt and stops on a missing
or mismatched key instead of silently generating a replacement.

A missing **source database SSL root certificate** is separate from the
credential-key error. Source profiles that use certificate verification need
the CA mounted read-only and `ssl_root_cert` set to its container path, such as
`/run/bizmatic-certs/root.crt`. Choose SSL mode according to the source server's
policy; do not disable certificate checks to fix a credential-key failure.
The internal Compose PostgreSQL service does not require a root certificate.

## Timeouts, preview and HTTPS

`REQUEST_TIMEOUT_SECONDS` defaults to 600 seconds for synchronous Gunicorn
workers. Nginx derives a timeout 30 seconds longer. Provider timeouts default to
120 seconds; repair calls and batches can multiply request time. Increase the
request budget for slow models or large full-source reviews. When exceeding the
default budget, also extend Compose `stop_grace_period` in your override so an
upgrade does not interrupt long work. Docker does not make the synchronous
workflows into background jobs. Check LLM activity before retrying a timed-out
request, because it may already have created a record.

Nginx serves PDF.js `.mjs` modules as `application/javascript`, WASM with the
standard MIME table, and collected static files with debug disabled. This fixes
the Ubuntu PDF preview MIME mismatch. Upload originals remain private Django
responses. `CLIENT_MAX_BODY_SIZE=128m` is the total upload-request limit; format
extraction limits remain those documented in the root README.

The default is HTTP on a trusted local network. If a trusted HTTPS terminator
forwards to the loopback-bound Compose proxy, set `PUBLIC_SCHEME=https`,
`DJANGO_SECURE_COOKIES=true`, and HTTPS entries in
`DJANGO_CSRF_TRUSTED_ORIGINS`, then recreate app/proxy. Add the public DNS name to
`DJANGO_ALLOWED_HOSTS`. The Compose proxy overwrites forwarded headers and the
Gunicorn port is never published. The stack does not provision TLS certificates.

## Operations, backups and restore

```sh
./deploy/compose logs --tail 100 app proxy db
./deploy/compose exec app python manage.py createsuperuser
./deploy/compose exec app python manage.py check
./deploy/compose exec app python -m pip check
```

Django admin users do not add a login requirement to the business workspace.
Health is available at `/healthz/` and returns 503 without database details when
the application database is unavailable. Bootstrap errors and migration failures
stop web-server startup rather than serving an incomplete installation. Do not
scale app replicas during bootstrap; migrations/static collection are designed
for one app container with configurable Gunicorn workers.

For a consistent backup, stop app/proxy first and retain the database, originals,
key and `.env.docker` together in restricted storage:

```sh
umask 077
mkdir -p /secure/bizmatic-backup
./deploy/compose stop proxy app
./deploy/compose exec -T db sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > /secure/bizmatic-backup/database.dump
./deploy/compose run --rm --no-deps -T app tar -C /var/lib/bizmatic -czf - uploads keys > /secure/bizmatic-backup/files-and-key.tar.gz
cp .env.docker /secure/bizmatic-backup/environment
./deploy/compose up -d --wait
```

Restore into a fresh, intentionally selected deployment with matching settings:
start `db` only, restore `database.dump` using `pg_restore --no-owner`, then
restore uploads/key using a one-off app container and `tar --no-same-owner`.
Verify the restored key's owner/mode and original paths before starting app.
Never mix a database backup with a newly generated key. PostgreSQL major-version
upgrades require their own backup/restore or pg_upgrade plan, not an image-tag
change against the same data directory.

For application upgrades, back up first, then `git pull` and
`./deploy/compose up -d --build --wait`. Restart/recreate preserves named volumes.
`./deploy/compose down` preserves data. **Do not use `down -v` for an installed
system**: it removes database, uploads, key and model volumes. The application and
proxy images are built locally; no private source or data is pushed to a registry.

## Validation

`python3 deploy/smoke.py --base-url URL` checks readiness, AP/AR pages, PDF.js,
WASM and CSS without writing data. `--write-fixture` additionally uploads a small
synthetic TXT, verifies extraction and downloads the original; use it only on a
disposable test stack. Unit tests cover key preservation/recovery and health
failure responses. Container testing does not contact paid LLM providers. The CI workflow builds
and smoke-tests the complete stack on Ubuntu, then runs the full Django suite
against PostgreSQL as well as the separate SQLite and frontend suites.


## Troubleshooting a local Ubuntu cutover

- **Port 8005 is allocated:** keep the old installation running until backup is
  complete, then stop its listener for cutover or choose a different Docker port.
  Regenerating an existing environment file is unnecessary; update port/origins
  explicitly if changing the address.
- **Original download returns 404:** verify the saved storage_path and the legacy
  mount path. Starting a volume at the new uploads path does not relocate rows.
- **Credential key unavailable or cannot decrypt:** restore the matching original
  key; SSL root certificates do not repair this error.
- **Ollama connection refused:** localhost inside app means the app container.
  Use the configured host-gateway endpoint or the optional internal service.
- **Request timed out/non-JSON response:** inspect app/proxy logs and LLM activity,
  then adjust the common request budget and provider settings. Do not repeatedly
  submit a request that may already have created its accounting record.
- **CSRF or host rejection:** update allowed hosts and trusted origins to the
  actual scheme, host and port, then recreate app/proxy. Keep localhost and
  127.0.0.1 allowed for internal health checks.
- **PDF preview still shows the old error after an upgrade:** hard-refresh the
  page and verify both PDF.js module responses are application/javascript.
