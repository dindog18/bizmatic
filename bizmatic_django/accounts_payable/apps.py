from importlib import import_module

from django.apps import AppConfig


class AccountsPayableConfig(AppConfig):
    name = "accounts_payable"

    def ready(self):
        # Load the standard Django signal handlers after all models are ready.
        import_module("accounts_payable.signals")
