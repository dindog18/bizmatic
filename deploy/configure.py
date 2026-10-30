"""Compatibility entry point; prefer ./bizmatic init for interactive setup/help."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deploy.cli import create_configuration


def configure(output, host, port, **storage):
    return create_configuration(output, host, port, **storage)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=8005)
    parser.add_argument('--output', default='.env.docker')
    args = parser.parse_args()
    configure(args.output, args.host, args.port)
    print(f'Created {args.output}. Review it before starting Compose.')
