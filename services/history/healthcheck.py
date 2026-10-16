"""Docker HEALTHCHECK for history: the liveness route answers 200."""
import os
import sys
import urllib.request

try:
    with urllib.request.urlopen(f"http://127.0.0.1:{os.environ.get('PORT', '8002')}/health", timeout=3) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception as exc:
    sys.exit(f"unhealthy: {exc}")
