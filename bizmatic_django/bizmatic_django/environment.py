"""Shared project configuration for Django and standalone extraction services."""

import os
from pathlib import Path

from dotenv import load_dotenv


# Resolve from this module so commands work from any working directory.
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_project_env() -> None:
    """Load the project .env without replacing explicit process variables.

    Missing files are allowed for deployments and CI configured entirely through
    the environment. Restart the process after editing .env to reload its values.
    """
    if os.environ.get('BIZMATIC_LOAD_PROJECT_ENV', 'true').lower() not in {'0', 'false', 'no', 'off'}:
        load_dotenv(dotenv_path=ENV_PATH, override=False)


def get_env(name: str, default: str = "") -> str:
    """Read configuration consistently, including from standalone services."""
    load_project_env()
    return os.environ.get(name, default)
