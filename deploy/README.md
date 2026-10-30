# Running Bizmatic

Docker with SQLite is the default. Native `python manage.py runserver` remains
supported, with no Docker dependency. The repository includes a standard-library
`bizmatic` command; Python 3.9+ on Linux/macOS is enough to use its help and configuration wizard.

## Quick start: Docker + SQLite

Install Docker Engine and Compose 2.30+ using the [official Ubuntu guide](https://docs.docker.com/engine/install/ubuntu/).
Run commands as your regular service account with Docker access, not with sudo.
From the repository root:

```sh
./bizmatic init
# Review .env.docker: paths, allowed hosts, LAN binding and LLM provider settings.
./bizmatic start
./bizmatic status
./bizmatic stop
```

`init` prompts for your SQLite file, uploads directory and credential-key
folder. Pressing Enter accepts the displayed user-owned folders under
`.bizmatic/`. It generates a private `.env.docker` with a random Django secret,
without overwriting an existing environment file, database or key. The key
itself is provisioned on first startup only when safe. No API keys, models or
business records are supplied automatically.

For explicit configuration, automation, or an Ubuntu server:

```sh
./bizmatic init --yes --host 192.168.0.175 --port 8005 \
  --database-file /srv/bizmatic/data/db.sqlite3 \
  --uploads-dir /srv/bizmatic/uploads \
  --key-dir /srv/bizmatic/keys
./bizmatic doctor
./bizmatic start
```

Choose folders writable by your service account. The app image builds with that
account's UID/GID so bind mounts remain writable without world-readable
permissions. The source tree inside the production image stays root-owned and
the app runs without root. Do not use application source or system folders as
writable database storage: SQLite needs its directory for journals as well as
the database file. Nonexistent folders are created with mode 0700.

The listener remains `127.0.0.1:8005` unless you set
`BIZMATIC_BIND_ADDRESS` to the Ubuntu server's LAN IP in `.env.docker`.
`--host` configures allowed hosts and CSRF origins, not network exposure. Open
`http://SERVER_IP:8005/documents/` after configuring the bind address.
The business workspace requires a trusted LAN/VPN or an authenticated reverse
proxy; it has no application login or tenant isolation. Docker-published ports
can bypass UFW; see [Docker's firewall notes](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations).

To type `bizmatic start` rather than `./bizmatic start`, add the checkout to PATH
or create a symlink:

```sh
mkdir -p "$HOME/.local/bin"
ln -s /absolute/path/to/bizmatic/bizmatic "$HOME/.local/bin/bizmatic"
# Ensure $HOME/.local/bin is on PATH in your shell configuration.
bizmatic help
```

## Commands

| Command | Behavior |
| --- | --- |
| `bizmatic init` | Prompt for paths and create a new private Docker configuration |
| `bizmatic start` | Build the current source and start app/proxy in the background |
| `bizmatic stop` | Stop containers; retain database, originals and keys |
| `bizmatic update` | Rebuild current UI/backend/dependencies, then recreate containers |
| `bizmatic start --dev` | Start Docker with live source, template and static reload |
| `bizmatic update --production` | Return to image-based production mode |
| `bizmatic restart` | Restart without rebuilding; use update for production code changes |
| `bizmatic status` | Show container status |
| `bizmatic logs --follow app proxy` | Follow selected service logs |
| `bizmatic doctor` | Check configuration, Docker and writable host directories |
| `bizmatic config` | Show storage locations without printing secrets |
| `bizmatic manage check` | Run a Django management command inside Docker |
| `bizmatic runserver 127.0.0.1:8000` | Run native Django in the foreground |
| `bizmatic start --local` | Shortcut to native runserver |
| `bizmatic help COMMAND` | Show command options |
| `bizmatic compose -- ...` | Advanced Compose passthrough using the selected backend/mode |

Use `--env-file /private/location/runtime.env` to select a user-provided Docker
configuration. `BIZMATIC_ENV_FILE` is also supported. The runtime file uses
literal `NAME=value` assignments: do not surround values with shell quotes.
Use the provided `.env.docker.example` format, including the BIZMATIC host paths.
`--project-name NAME` isolates containers/volumes, but choose separate host data
folders too if you need an independent instance.

There is no data-deletion command. `stop` does not call `down -v`. Do not use raw
Compose volume-deletion commands on an installed system.

## Configure paths, providers and environment

Edit `.env.docker` before starting. `init` generates defaults; you supply the
server address, paths, provider endpoints, model names and API keys appropriate
for your system. No developer `.env` or local database is baked into the image.

| Setting | Meaning |
| --- | --- |
| `BIZMATIC_DATABASE_FILE` | Absolute host SQLite filename |
| `BIZMATIC_DATA_DIR` | Its parent directory, also mounted for SQLite journals |
| `BIZMATIC_UPLOADS_DIR` | Absolute host directory for original files |
| `BIZMATIC_KEY_DIR` | Private host folder containing `db-extraction.key` |
| `BIZMATIC_UID`, `BIZMATIC_GID` | Account that builds/runs the app and owns host data |
| `DJANGO_SECRET_KEY` | Stable installation secret; generated once or supplied by you |
| `DJANGO_ALLOWED_HOSTS` | Explicit host names/IPs, including localhost/127.0.0.1 for health checks |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Actual public scheme, host and port |
| `BIZMATIC_BIND_ADDRESS`, `BIZMATIC_PORT` | Nginx listener |
| `DOC_EXTRACTION_*`, `ROUTER_*`, `ACCOUNTS_*`, `CONFIG_ASSISTANT_*` | Provider/model/key/timeout settings |

Host folders are mounted at the **same absolute paths inside Docker**. This
preserves stored original-file paths and allows an intentionally configured
native installation to use the same database and originals. Switching modes
does not move data or rewrite records. Do not run native and Docker writers
against the same SQLite file simultaneously. Use private local disk rather
than an NFS/network share; back up before switching modes or schema versions.

The app uses one Gunicorn worker by default and a 30-second SQLite lock timeout.
SQLite still serializes writes; for sustained concurrent accounting workloads,
use the explicit PostgreSQL option below instead of merely increasing workers.
The app has default 2 GiB/two-CPU/256-process limits, configurable for your host.

Add other provider variables from `bizmatic_django/.env.example` to your Docker
file. Models remain independent per module. API keys/URLs can fall back to the
matching DOC_EXTRACTION setting. Native `.env` is deliberately not loaded by
Docker, including development mode, so credentials cannot silently come from a
second configuration. Run `bizmatic update` after changing runtime settings.
Do not post `compose config` output publicly; it contains resolved secrets.

## UI/UX and backend updates

Production mode runs an image of the code. After editing or updating your source:

```sh
./bizmatic update
```

The old containers continue serving during the build; Compose recreates them
when the new image is ready. Expect a brief restart, not a zero-downtime
migration. Automatic migrations and static collection run on startup. Host
SQLite/originals/key files and the private environment file remain intact.
Back up before updates that change the database schema. The CLI does not run
`git pull`, overwrite uncommitted work, or reset secrets.

For active frontend/backend development:

```sh
./bizmatic start --dev
# Edit Python, templates, CSS and JS; refresh the browser for UI changes.
./bizmatic logs --follow app
```

Development mode bind-mounts source read-only into app, reloads Python workers,
rereads templates without enabling Django debug error pages, and serves local
static files directly with `Cache-Control: no-store`. The successful mode choice
is remembered for subsequent start/update commands. Changes to dependencies,
Dockerfiles, or runtime `.env` still need `bizmatic update`. New Django apps or static directory
names may need a corresponding mount in `compose.dev.yaml`.

## Native Python / runserver

Docker is recommended, but the original workflow remains available:

```sh
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp bizmatic_django/.env.example bizmatic_django/.env  # new installations only
# Edit this native .env with your secret, paths, providers and models.
cd bizmatic_django
python manage.py init_db_credential_key
python manage.py migrate
python manage.py runserver
```

Keep an existing native `.env` instead of overwriting it. It uses normal dotenv
syntax, including quoted values, unlike the raw Docker runtime file. From the
repository root, `./bizmatic runserver` uses `.venv/bin/python` when available
and otherwise the current Python interpreter. Ctrl+C stops native runserver.
Docker is not checked or started in this mode. Native runserver is intended for
development, not an internet-facing production service.

To intentionally reuse the configured Docker SQLite/originals/key on the host,
stop Docker and set these native `.env` values to the paths shown by
`bizmatic config`:

```dotenv
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=/srv/bizmatic/data/db.sqlite3
LOCAL_FILE_STORAGE_PATH=/srv/bizmatic/uploads
DB_EXTRACTION_CREDENTIAL_KEY_FILE=/srv/bizmatic/keys/db-extraction.key
```

Keep or supply native provider credentials/model settings as well. A container
Ollama hostname is not a host-native endpoint. Existing relative original paths
may need verified mounts/remapping; prefer absolute paths before sharing modes.

## Optional PostgreSQL and existing Docker installations

PostgreSQL is no longer required by the default stack. For a new PostgreSQL app:

```sh
./bizmatic init --database postgres --env-file .env.postgres --yes
./bizmatic start --env-file .env.postgres
```

The CLI includes `compose.postgres.yaml` only for that explicit backend. Its
application database lives in a named volume; originals and keys still use your
chosen host directories. External read-only source PostgreSQL profiles remain
available with either application database backend.

An older Docker configuration from commit 00305f6 used named PostgreSQL/uploads/
key volumes. The CLI refuses to start it without configured host paths instead
of silently replacing storage. Keep using that revision until you have backed
up and planned the move. Export originals and the original key to the selected
host directories. Keep PostgreSQL selected to reuse its database, or plan a
separate verified database migration to SQLite. No automated PostgreSQL-to-SQLite
conversion is performed. The `static` volume is regenerable; if changing the
service-account UID, repair its ownership explicitly or recreate only that cache.
Never delete database or key volumes to fix a permissions problem.

## Ollama, SSL certificates and HTTPS

For host Ollama, use `http://host.docker.internal:11434` from Docker. Linux's
host-gateway mapping is included; Ollama needs a bridge-reachable listener with
appropriate network restrictions. Optional internal Ollama is available through
`bizmatic compose -- --profile ollama up -d`; set its base URL to
`http://ollama:11434`, then pull your chosen model explicitly with
`bizmatic compose -- --profile ollama exec ollama ollama pull YOUR_MODEL`.
No models or GPU drivers are downloaded automatically. A native runserver uses
its own reachable host endpoint, normally `http://localhost:11434`.

A source PostgreSQL profile's localhost also refers to the app container; use a
reachable host address. Mount CA certificates read-only through an explicit
Compose override and set ssl_root_cert to that container path. A missing SSL CA
is distinct from a missing credential key: do not rotate the key or disable
certificate verification to work around the other error.

HTTP is the default on a trusted local network. For an authenticated HTTPS
terminator in front of the loopback-bound proxy, set `PUBLIC_SCHEME=https`,
`DJANGO_SECURE_COOKIES=true`, HTTPS CSRF origins and the public allowed host.
The proxy overwrites forwarded headers; Gunicorn's port is never published.

## Backups and troubleshooting

Stop all writers before a SQLite backup. Copy the database, complete uploads
folder, original key and private environment settings into restricted backup
storage. `bizmatic config` shows their paths without printing secrets. Preserve
key mode 0600 and service-account ownership. Restore matching database/key pairs;
startup stops if saved source passwords cannot decrypt. Never generate a new key
to make an existing encrypted database start. PostgreSQL backups need pg_dump/
pg_restore in addition to the originals/key/settings backup.

`REQUEST_TIMEOUT_SECONDS=600` controls workers; Nginx waits 30 seconds longer.
Increase this for slow provider repairs/batches and extend stop_grace_period if
using a longer budget. Requests remain synchronous; inspect LLM activity before
retrying a timeout that may already have created a record. PDF.js `.mjs` is served
as JavaScript; hard-refresh an old browser cache after deployment changes.

Port conflicts: stop the previous listener after backup or choose another port
and matching allowed origins. Missing original files: verify saved paths and
mounts before changing database rows. Permission failures: use the same service
account that initialized the directories, verify UID/GID and key mode, then
rebuild after changing account settings. Do not use chmod 777.

For read-only smoke checks: `python3 deploy/smoke.py --base-url URL`.
`--write-fixture` adds a synthetic TXT document and is for disposable test
instances only. CI tests default SQLite and optional PostgreSQL Docker stacks,
CLI behavior, native Django tests, and upload/restart persistence.
