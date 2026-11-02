"""A tiny in-process cache with the same call shape as the hosted service's
response cache: cached_call(namespace, data, fn, ttl) runs fn(**data) once and
serves the result for `ttl` (a timedelta). Each hit is a fresh copy (stored as
JSON), so a caller that edits a result never changes the cached one. Lives only
as long as the process."""
import json
import threading
import time

_store = {}
_lock = threading.Lock()


def cached_call(namespace, data, fn, ttl, cache=True, refresh=False):
    key = namespace + ":" + json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
    now = time.time()
    if cache and ttl and not refresh:
        with _lock:
            hit = _store.get(key)
        if hit and hit[0] > now:
            return json.loads(hit[1])
    result = fn(**data)
    if cache and ttl:
        seconds = ttl.total_seconds() if hasattr(ttl, "total_seconds") else float(ttl)
        with _lock:
            _store[key] = (now + seconds, json.dumps(result, ensure_ascii=False))
    return result
