from importlib import import_module

from django.apps import AppConfig


class AccountsReceivableConfig(AppConfig):
    name = "accounts_receivable"

    def ready(self):
        # Load the standard Django signal handlers after all models are ready.
        import_module("accounts_receivable.signals")
