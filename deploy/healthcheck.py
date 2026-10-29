import urllib.request

request = urllib.request.Request('http://127.0.0.1:8000/healthz/', headers={'Host': 'localhost'})
with urllib.request.urlopen(request, timeout=4) as response:
    if response.status != 200:
        raise SystemExit(1)
