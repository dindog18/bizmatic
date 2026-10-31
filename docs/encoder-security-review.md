# Encoder and Router security review

Scope: the Encoder implementation and Router integration in this change, including MCP transport, credential configuration, tool selection, chat corrections, execution approval, retries and reset. This is a targeted source review, not an exhaustive repository or dependency audit. The Codex Security workbench scan remains partial; generated output directories and unchanged vendor assets are outside this review.

## Fixed

Remote Streamable HTTP endpoints accepted plain HTTP despite supporting bearer tokens and secret headers. An on-path network observer could read credentials and document payloads. Connection validation now rejects non-loopback plain HTTP before resolving credentials or creating the client. Localhost, IPv4/IPv6 loopback HTTP and remote HTTPS remain supported. Tests cover remote addresses, misleading localhost suffixes, and supported endpoint forms.

## Controls inspected

- Encoder access checks the actual peer and Host for loopback, and is disabled by default. This application is intended for trusted local development, not public deployment.
- Configuration, chat correction, execution and reset use CSRF-protected POST handlers. GET requests do not execute business tools.
- The backend requires enabled connections and approved tool names, signed current payload confirmations, source/route approvals, and matching live tool schemas before invocation.
- Credentials use Database Connections' encrypted field. Transport exceptions are sanitized. The MCP SDK handles redirect origin restrictions; no custom unrestricted redirect client is introduced.
- Chat cannot call MCP tools. Markdown rendering disables raw HTML, links and images. User corrections are revision-bound and cycle-bound.
- Reset preserves audit records, stable idempotency keys, and unknown-outcome reconciliation checks. Processing requests block reset.

## Review limits

No production ERP credentials or business mutations were used. No claim is made that every vulnerability has been found. Additional review should cover deployment/proxy topology and installed dependency advisories before any public exposure.
