"""Development-mode integration test; reversibly edits three source fixtures."""
import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def check_reload(base_url):
    root = Path(__file__).resolve().parent.parent
    paths = [root / 'bizmatic_django/bizmatic_django/health.py',
             root / 'bizmatic_django/document_extraction/templates/document_extraction/base.html',
             root / 'bizmatic_django/document_extraction/static/document_extraction/app.css']
    originals = {path:path.read_bytes() for path in paths}
    marker = 'bizmatic-live-reload-check'
    try:
        health = originals[paths[0]].decode()
        if "{'status': 'ok'}" not in health:
            raise AssertionError('Health fixture changed; update the reload test.')
        paths[0].write_text(health.replace("{'status': 'ok'}", "{'status': 'ok', 'reload_check': '" + marker + "'}"))
        paths[1].write_bytes(originals[paths[1]] + ('\n<!-- ' + marker + ' -->\n').encode())
        paths[2].write_bytes(originals[paths[2]] + ('\n/* ' + marker + ' */\n').encode())
        for attempt in range(30):
            try:
                with urllib.request.urlopen(base_url + '/healthz/', timeout=3) as response:
                    ready = json.load(response).get('reload_check') == marker
                if ready:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        else:
            raise AssertionError('Python workers did not reload the changed source.')
        with urllib.request.urlopen(base_url + '/documents/', timeout=10) as response:
            assert marker in response.read().decode(), 'Template change was cached'
        with urllib.request.urlopen(base_url + '/static/document_extraction/app.css', timeout=10) as response:
            assert marker in response.read().decode(), 'CSS source was not served directly'
            assert 'no-store' in response.headers.get('Cache-Control',''), 'Development static cache is enabled'
        print('Live Python, template and static reload checks passed.')
    finally:
        for path, content in originals.items():
            path.write_bytes(content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8005')
    parser.add_argument('--allow-source-edits', action='store_true', required=True,
                        help='Authorize temporary source edits, restored in finally; use a disposable dev stack')
    args = parser.parse_args()
    check_reload(args.base_url.rstrip('/'))
