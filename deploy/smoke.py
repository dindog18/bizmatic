"""Check a running deployment; optional writes are for disposable test stacks only."""
import argparse
import http.cookiejar
import re
import urllib.request
import uuid


def smoke(base_url, write_fixture=False):
    base_url = base_url.rstrip('/')
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    for path in ['/healthz/', '/documents/', '/accounts-payable/', '/accounts-receivable/',
                 '/accounts-receivable/configuration/new/?target=purchase_order&source=document']:
        with opener.open(base_url + path, timeout=15) as response:
            assert response.status == 200, path
    for asset, content_type in [('pdf.min.mjs', 'application/javascript'), ('pdf.worker.min.mjs', 'application/javascript'),
                                ('wasm/openjpeg.wasm', 'application/wasm')]:
        path = '/static/document_extraction/vendors/pdfjs/' + asset
        with opener.open(base_url + path, timeout=15) as response:
            assert response.headers.get_content_type() == content_type, (path, response.headers.get_content_type())
    with opener.open(base_url + '/static/document_extraction/app.css', timeout=15) as response:
        assert response.headers.get_content_type() == 'text/css'
    if write_fixture:
        with opener.open(base_url + '/documents/upload/', timeout=15) as response:
            html = response.read().decode()
        csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
        boundary = 'bizmatic-' + uuid.uuid4().hex
        content = 'Bizmatic Docker smoke fixture ' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="csrfmiddlewaretoken"\r\n\r\n{csrf}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="docker-smoke.txt"\r\n'
                f'Content-Type: text/plain\r\n\r\n{content}\r\n--{boundary}--\r\n').encode()
        request = urllib.request.Request(base_url + '/documents/upload/', data=body, headers={
            'Content-Type': 'multipart/form-data; boundary=' + boundary, 'Origin':base_url})
        with opener.open(request, timeout=30) as response:
            assert response.status == 200
        with opener.open(base_url + '/documents/', timeout=15) as response:
            listing = response.read().decode()
        # Only the fresh smoke fixture is selected; never alter existing rows.
        match = re.search(r'href="(/documents/(\d+)/)"[^>]*>\s*docker-smoke.txt', listing)
        if not match:
            raise AssertionError('Uploaded fixture is missing from document list.')
        with opener.open(base_url + match.group(1), timeout=15) as response:
            detail = response.read().decode()
        assert content in detail, 'Text extraction did not persist'
        with opener.open(base_url + match.group(1) + 'original/', timeout=15) as response:
            assert response.read().decode() == content
        print('Synthetic upload, extraction and original download passed.')
    print('Readiness, AP/AR pages, PDF.js modules, WASM and CSS passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8005')
    parser.add_argument('--write-fixture', action='store_true', help='Create a synthetic TXT document; disposable test environments only.')
    args = parser.parse_args()
    smoke(args.base_url, args.write_fixture)
