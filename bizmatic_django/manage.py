#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys

from bizmatic_django.environment import load_project_env


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bizmatic_django.settings")
    # Load configuration before runserver applies its local debug fallback.
    load_project_env()
    if len(sys.argv) > 1 and sys.argv[1] == "runserver":
        # Django serves development static assets only when DEBUG is enabled.
        # Limit this default to runserver and respect explicit environment values.
        os.environ.setdefault("DJANGO_DEBUG", "true")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
