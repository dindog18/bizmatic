"""Generate fresh Docker configuration without printing secrets or overwriting files."""
import argparse
import os
import secrets
from pathlib import Path


def configure(output, host, port):
    if not host or any(char in host for char in '\r\n,/:$# ') or host == '*':
        raise ValueError('Use one IPv4 address or host name, without a scheme or port.')
    if not 1 <= port <= 65535:
        raise ValueError('Port must be between 1 and 65535.')
    template = Path(__file__).resolve().parent.parent / '.env.docker.example'
    text = template.read_text()
    text = text.replace('replace-with-generated-secret', secrets.token_hex(32))
    text = text.replace('replace-with-generated-password', secrets.token_hex(24))
    hosts = ','.join(dict.fromkeys(['localhost', '127.0.0.1', host]))
    origins = ','.join(f'http://{value}:{port}' for value in hosts.split(','))
    text = text.replace('DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1', 'DJANGO_ALLOWED_HOSTS=' + hosts)
    text = text.replace('DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8005,http://127.0.0.1:8005', 'DJANGO_CSRF_TRUSTED_ORIGINS=' + origins)
    text = text.replace('BIZMATIC_PORT=8005', f'BIZMATIC_PORT={port}')
    # Binding remains loopback until the operator explicitly enables LAN access.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(text)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=8005)
    parser.add_argument('--output', default='.env.docker')
    args = parser.parse_args()
    configure(args.output, args.host, args.port)
    print(f'Created {args.output} with permissions 0600. Review it before starting Compose.')
