# Accounts payable

AP keeps its own models and matching/settlement rules in `services/reconciliation.py`.
The workspace, configuration, extraction, and import services are shared with AR
through an explicit module argument. See the [AP/AR backend guide](../accounts_receivable/README.md).
