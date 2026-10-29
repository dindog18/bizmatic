"""Finite request budgets for synchronous LLM and full database-review requests."""
import os

bind = '0.0.0.0:8000'
workers = int(os.getenv('WEB_WORKERS', '2'))
worker_class = 'sync'
timeout = int(os.getenv('REQUEST_TIMEOUT_SECONDS', '600'))
if timeout < 1:
    raise ValueError('REQUEST_TIMEOUT_SECONDS must be positive.')
graceful_timeout = timeout
accesslog = '-'
errorlog = '-'
capture_output = True
forwarded_allow_ips = '*'
# Only the private Compose proxy reaches this unpublished port. It overwrites
# forwarded headers instead of trusting headers received from clients.
secure_scheme_headers = {'X-FORWARDED-PROTO': 'https'}
