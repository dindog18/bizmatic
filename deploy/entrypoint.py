"""Initialize a deployment only for normal web-server startup, then replace PID 1."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Pass a command to the container.')
    if sys.argv[1] == 'gunicorn':
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bizmatic_django.settings')
        import django
        django.setup()
        from bizmatic_django.deployment import prepare_application
        prepare_application()
    os.execvp(sys.argv[1], sys.argv[1:])
