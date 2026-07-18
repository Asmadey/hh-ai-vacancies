"""Single HTTP entrypoint. Every module calls request() -> easy to mock in tests."""
import json
import urllib.request
import urllib.error


class HttpResponse:
    def __init__(self, status, body_bytes=b"", headers=None):
        self.status = status
        self.body = body_bytes
        self.headers = headers or {}

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except Exception:
            return {}

    @property
    def text(self):
        try:
            return self.body.decode("utf-8")
        except Exception:
            return ""


class NetworkError(Exception):
    """DNS/timeout/connection failure — API considered down."""


def request(method, url, headers=None, data=None, timeout=25):
    """data: bytes (pre-encoded). Returns HttpResponse for ANY http status (no raise on 4xx/5xx)."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return HttpResponse(resp.status, resp.read(), dict(resp.headers))
    except urllib.error.HTTPError as e:
        return HttpResponse(e.code, e.read(), dict(e.headers or {}))
    except Exception as e:  # URLError, timeout, ConnectionReset...
        raise NetworkError(str(e))
