"""Standard-library CLI for Docker by default and native runserver when requested."""
import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH_KEYS = ('BIZMATIC_DATA_DIR', 'BIZMATIC_DATABASE_FILE', 'BIZMATIC_UPLOADS_DIR', 'BIZMATIC_KEY_DIR')


def read_config(path):
    if not path.is_file():
        raise ValueError(f'Configuration not found: {path}. Run bizmatic init first.')
    values = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key.strip()):
            raise ValueError(f'Invalid environment assignment at line {number}. Use NAME=value.')
        if value.startswith(('"', "'")):
            raise ValueError(f'Quoted value at line {number}: Docker configuration uses literal, unquoted values.')
        values[key.strip()] = value
    return values


def host_path(value):
    if any(char in str(value) for char in '\r\n\x00'):
        raise ValueError('Paths cannot contain line breaks or NUL bytes.')
    return Path(value).expanduser().resolve()


def validate_storage_directories(directories):
    for directory in directories:
        directory = directory.resolve()
        if directory == ROOT.resolve() or any(directory.is_relative_to((ROOT / name).resolve()) for name in ('bizmatic_django', 'deploy', '.git')):
            raise ValueError('Choose private data directories outside the application source; move a stopped legacy SQLite database to a private data folder first.')
        if directory in map(Path, ('/', '/app', '/etc', '/usr', '/dev', '/proc', '/sys')):
            raise ValueError('The selected path would hide a required container system directory.')


def create_configuration(output, host='localhost', port=8005, *, database_file=None,
                         uploads_dir=None, key_dir=None, database='sqlite', dev=False):
    output = host_path(output)
    if output.exists():
        raise FileExistsError(f'{output} already exists; edit it or choose --env-file. It was not overwritten.')
    if not host or any(char in host for char in '\r\n\t,/:$# ') or host == '*':
        raise ValueError('Use one IPv4 address or host name without a scheme or port.')
    if not 1 <= port <= 65535:
        raise ValueError('Port must be between 1 and 65535.')
    if os.getuid() == 0:
        raise ValueError('Run init as your regular service account, not sudo, so the bind mounts remain user-owned.')
    database_file = host_path(database_file or ROOT / '.bizmatic/data/db.sqlite3')
    uploads_dir = host_path(uploads_dir or ROOT / '.bizmatic/uploads')
    key_dir = host_path(key_dir or ROOT / '.bizmatic/keys')
    directories = (database_file.parent, uploads_dir, key_dir)
    validate_storage_directories(directories)
    text = (ROOT / '.env.docker.example').read_text()
    replacements = {'replace-with-generated-secret':secrets.token_hex(32),
                    '__DATA_DIR__':str(database_file.parent), '__DATABASE_FILE__':str(database_file),
                    '__UPLOADS_DIR__':str(uploads_dir), '__KEY_DIR__':str(key_dir),
                    '__UID__':str(os.getuid()), '__GID__':str(os.getgid())}
    for key, value in replacements.items():
        text = text.replace(key, value)
    hosts = ','.join(dict.fromkeys(['localhost', '127.0.0.1', host]))
    origins = ','.join(f'http://{value}:{port}' for value in hosts.split(','))
    text = text.replace('DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1', 'DJANGO_ALLOWED_HOSTS=' + hosts)
    text = text.replace('DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8005,http://127.0.0.1:8005', 'DJANGO_CSRF_TRUSTED_ORIGINS=' + origins)
    text = text.replace('BIZMATIC_PORT=8005', f'BIZMATIC_PORT={port}')
    text += f'\nBIZMATIC_DEV_MODE={str(dev).lower()}\n'
    if database == 'postgres':
        text = text.replace('DB_ENGINE=django.db.backends.sqlite3', 'DB_ENGINE=django.db.backends.postgresql')
        text += '\nDB_NAME=bizmatic\nDB_USER=bizmatic\nDB_PASSWORD=' + secrets.token_hex(24) + '\n'
    for directory in directories:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(text)
    return output


def configuration(args):
    path = host_path(args.env_file or os.getenv('BIZMATIC_ENV_FILE', ROOT / '.env.docker'))
    values = read_config(path)
    if any(not values.get(key) for key in (*PATH_KEYS, 'BIZMATIC_UID', 'BIZMATIC_GID')):
        raise ValueError('This is an older Docker configuration without host storage paths. See deploy/README.md before migrating; existing volumes were not changed.')
    for key in PATH_KEYS:
        if not Path(values[key]).is_absolute():
            raise ValueError(f'{key} must be an absolute host path. Use bizmatic init to configure paths.')
    validate_storage_directories([Path(values[key]) for key in ('BIZMATIC_DATA_DIR','BIZMATIC_UPLOADS_DIR','BIZMATIC_KEY_DIR')])
    if Path(values['BIZMATIC_DATABASE_FILE']).parent != Path(values['BIZMATIC_DATA_DIR']):
        raise ValueError('The SQLite file must be inside BIZMATIC_DATA_DIR.')
    return path, values


def state_file(path):
    return ROOT / '.bizmatic' / ('cli-' + hashlib.sha256(str(path).encode()).hexdigest()[:12] + '.json')


def compose(args, values, path, dev=None):
    if not shutil.which('docker'):
        raise ValueError('Docker is not installed. See deploy/README.md or use bizmatic runserver.')
    if dev is None:
        try:
            dev = json.loads(state_file(path).read_text())['dev']
        except (OSError, ValueError, KeyError):
            dev = values.get('BIZMATIC_DEV_MODE', 'false').lower() == 'true'
    command = ['docker', 'compose', '--project-directory', str(ROOT), '--env-file', str(path), '-f', str(ROOT / 'compose.yaml')]
    if values.get('DB_ENGINE', 'django.db.backends.sqlite3') == 'django.db.backends.postgresql':
        command += ['-f', str(ROOT / 'compose.postgres.yaml')]
    elif values.get('DB_ENGINE', 'django.db.backends.sqlite3') != 'django.db.backends.sqlite3':
        raise ValueError('Choose SQLite or PostgreSQL for the application database.')
    if dev:
        command += ['-f', str(ROOT / 'compose.dev.yaml')]
    if args.project_name:
        command += ['-p', args.project_name]
    env = {**values, **os.environ, 'BIZMATIC_ENV_FILE':str(path)}
    # Explicit file values determine runtime storage, not unrelated shell settings.
    for key in (*PATH_KEYS, 'BIZMATIC_UID', 'BIZMATIC_GID'):
        env[key] = values[key]
    return command, env, bool(dev)


def run_native(arguments):
    executable = ROOT / '.venv/bin/python'
    python = str(executable) if executable.is_file() else sys.executable
    return subprocess.run([python, 'manage.py', 'runserver', *arguments], cwd=ROOT / 'bizmatic_django').returncode


def parser():
    result = argparse.ArgumentParser(prog='bizmatic', description='Run Bizmatic with Docker + SQLite by default. Native python manage.py runserver is also supported.')
    result.add_argument('--env-file', help='User-provided literal Docker environment file (default .env.docker)')
    result.add_argument('--project-name', help='Separate Compose project name')
    commands = result.add_subparsers(dest='action')
    for action, help_text in [('init','Configure user-owned storage and a private environment file'),
                              ('start','Build and start Docker in the background'), ('stop','Stop Docker; keep all data'),
                              ('update','Rebuild UI/backend code and recreate containers; keep data'),
                              ('restart','Restart existing containers without rebuilding'), ('status','Show container status'),
                              ('logs','Show container logs'), ('doctor','Check Docker, configuration and filesystem access'),
                              ('config','Show non-secret storage settings'), ('manage','Run a Django command in Docker'),
                              ('compose','Advanced Compose passthrough with the selected backend and mode'),
                              ('runserver','Run native Django in the foreground; Docker is not required'),
                              ('help','Show help for a command')]:
        sub = commands.add_parser(action, help=help_text)
        sub.add_argument('--env-file', default=argparse.SUPPRESS)
        sub.add_argument('--project-name', default=argparse.SUPPRESS)
        if action == 'init':
            sub.add_argument('--host', default='localhost'); sub.add_argument('--port', type=int, default=8005)
            sub.add_argument('--database-file'); sub.add_argument('--uploads-dir'); sub.add_argument('--key-dir')
            sub.add_argument('--database', choices=['sqlite','postgres'], default='sqlite')
            sub.add_argument('--dev', action='store_true'); sub.add_argument('--yes', action='store_true', help='Use supplied flags/defaults without interactive prompts')
        if action in ('start','update'):
            modes = sub.add_mutually_exclusive_group()
            modes.add_argument('--dev', dest='dev', action='store_true', default=None)
            modes.add_argument('--production', dest='dev', action='store_false')
            sub.add_argument('--no-build', action='store_true'); sub.add_argument('--wait-timeout', type=int, default=180)
        if action == 'start':
            sub.add_argument('--local', action='store_true', help='Run native Django in the foreground instead of Docker')
            sub.add_argument('--address', default='127.0.0.1:8000')
        if action == 'logs':
            sub.add_argument('--follow', '-f', action='store_true'); sub.add_argument('--tail', type=int, default=100)
            sub.add_argument('services', nargs='*')
        if action in ('runserver','manage','compose'):
            sub.add_argument('arguments', nargs=argparse.REMAINDER)
        if action == 'help':
            sub.add_argument('command', nargs='?')
    return result


def main(argv=None):
    cli = parser(); args = cli.parse_args(argv)
    if args.action in (None, 'help'):
        if args.action == 'help' and args.command:
            cli.parse_args([args.command, '--help'])
        else:
            cli.print_help()
        return 0
    try:
        if args.action == 'runserver':
            return run_native(args.arguments)
        if args.action == 'start' and args.local:
            return run_native([args.address])
        if args.action == 'init':
            if sys.stdin.isatty() and not args.yes:
                for attribute, label, default in [('database_file','SQLite database file',ROOT / '.bizmatic/data/db.sqlite3'),
                                                  ('uploads_dir','Original uploads folder',ROOT / '.bizmatic/uploads'),
                                                  ('key_dir','Credential key folder',ROOT / '.bizmatic/keys')]:
                    selected = getattr(args, attribute)
                    if not selected:
                        setattr(args, attribute, input(f'{label} [{default}]: ').strip() or str(default))
            path = create_configuration(args.env_file or os.getenv('BIZMATIC_ENV_FILE', ROOT / '.env.docker'), args.host, args.port,
                database_file=args.database_file, uploads_dir=args.uploads_dir, key_dir=args.key_dir, database=args.database, dev=args.dev)
            print(f'Created {path} (0600). Review your paths, host binding and provider settings, then run bizmatic start.')
            return 0
        path, values = configuration(args)
        if args.action in ('config','doctor'):
            print(f'Environment file: {path}')
            print('Application database: ' + values.get('DB_ENGINE', 'django.db.backends.sqlite3'))
            for key in PATH_KEYS:
                print(f'{key}={values[key]}')
            if args.action == 'config':
                return 0
            for key in ('BIZMATIC_DATA_DIR','BIZMATIC_UPLOADS_DIR','BIZMATIC_KEY_DIR'):
                directory = Path(values[key])
                if not directory.is_dir() or not os.access(directory, os.W_OK):
                    raise ValueError(f'{key} is missing or not writable by your service account.')
            command, env, _ = compose(args, values, path)
            subprocess.run(['docker','info','--format','Docker engine reachable'], check=True, env=env)
            subprocess.run(command + ['config','--quiet'], check=True, env=env)
            print('Docker configuration and storage checks passed. Run status to inspect readiness.')
            return 0
        command, env, dev = compose(args, values, path, getattr(args, 'dev', None))
        if args.action in ('start','update'):
            operation = ['up','-d','--wait','--wait-timeout',str(args.wait_timeout)]
            if not args.no_build:
                operation.append('--build')
        elif args.action == 'stop': operation = ['stop']
        elif args.action == 'restart': operation = ['restart']
        elif args.action == 'status': operation = ['ps']
        elif args.action == 'logs': operation = ['logs','--tail',str(args.tail)] + (['--follow'] if args.follow else []) + args.services
        elif args.action == 'compose':
            operation = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
        elif args.action == 'manage':
            if not args.arguments:
                raise ValueError('Pass a Django command, for example bizmatic manage check.')
            operation = ['exec','-T','app','python','manage.py',*args.arguments]
        subprocess.run(command + operation, env=env, cwd=ROOT, check=True)
        if args.action in ('start','update'):
            target = state_file(path); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({'dev':dev}))
            host = values.get('BIZMATIC_BIND_ADDRESS', '127.0.0.1')
            if host in ('127.0.0.1', '0.0.0.0'):
                host = 'localhost'
            print(f'Bizmatic started ({"development reload" if dev else "Docker"}). Open {values.get("PUBLIC_SCHEME","http")}://{host}:{values.get("BIZMATIC_PORT","8005")}/documents/')
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'bizmatic: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
