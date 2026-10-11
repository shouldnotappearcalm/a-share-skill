"""Bounded source workers, circuit breakers and transparent JSON caching."""
from concurrent.futures import Future
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import queue
import threading
import time
import uuid


class SourcePool:
    """Daemon workers keep timed-out libraries from blocking CLI exit or spawning forever."""
    def __init__(self, workers=12, backlog=48):
        self.jobs = queue.Queue(maxsize=backlog)
        for index in range(workers):
            threading.Thread(target=self._work, name=f"market-source-{index}", daemon=True).start()

    def _work(self):
        while True:
            future, fn = self.jobs.get()
            try:
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(fn())
                    except BaseException as exc:
                        future.set_exception(exc)
            finally:
                self.jobs.task_done()

    def submit(self, fn):
        future = Future()
        try:
            self.jobs.put_nowait((future, fn))
        except queue.Full:
            raise RuntimeError("source capacity exhausted; retry later")
        return future

    def call(self, fn, timeout):
        future = self.submit(fn)
        try:
            return future.result(timeout=max(0.01, timeout))
        except TimeoutError:
            future.cancel()
            raise TimeoutError(f"source timeout after {timeout:.2f}s") from None


_POOL = None
_LOCK = threading.RLock()
_FLIGHTS = {}
_HEALTH = {}


def call_source(fn, timeout):
    global _POOL
    with _LOCK:
        if _POOL is None:
            _POOL = SourcePool()
    return _POOL.call(fn, timeout)


def submit_source(fn):
    global _POOL
    with _LOCK:
        if _POOL is None:
            _POOL = SourcePool()
    return _POOL.submit(fn)


def circuit_ready(key):
    with _LOCK:
        return _HEALTH.get(key, (0, 0))[1] <= time.monotonic()


def source_result(key, success):
    with _LOCK:
        failures, until = _HEALTH.get(key, (0, 0))
        _HEALTH[key] = (0, 0) if success else (failures + 1, time.monotonic() + 30 if failures >= 2 else until)


def _cache_path(key):
    root = Path(os.environ.get("ASHARE_DATA_CACHE_DIR", Path(__file__).resolve().parents[1] / "cache"))
    return root / (sha256(key.encode()).hexdigest() + ".json")


def peek_cache(key):
    try:
        payload = json.loads(_cache_path(key).read_text())
        if payload.get("version") == 1 and isinstance(payload.get("created"), (int, float)) and isinstance(payload.get("fetched_at"), str) and "data" in payload:
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return None


def cached_fetch(key, loader, ttl, no_cache=False, cacheable=None):
    """Return a copy plus cache metadata; never silently serve expired data."""
    no_cache = no_cache or os.environ.get("ASHARE_NO_CACHE") == "1"
    cached = None if no_cache else peek_cache(key)
    if cached and 0 <= time.time() - cached["created"] < ttl:
        return deepcopy(cached["data"]), {"cache_hit": True, "fetched_at": cached["fetched_at"], "cache_ttl_seconds": ttl}
    with _LOCK:
        flight = _FLIGHTS.get(key)
        owner = flight is None
        if owner:
            flight = Future()
            _FLIGHTS[key] = flight
    if not owner:
        value, meta = flight.result(timeout=65)
        return deepcopy(value), dict(meta, request_coalesced=True)
    try:
        value = loader(None if no_cache else cached)
        fetched_at = datetime.now(timezone.utc).isoformat()
        meta = {"cache_hit": False, "fetched_at": fetched_at, "cache_ttl_seconds": ttl}
        if not no_cache and ttl > 0 and (cacheable is None or cacheable(value)):
            path = _cache_path(key)
            tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps({"version": 1, "created": time.time(), "fetched_at": fetched_at, "data": value}, ensure_ascii=False, allow_nan=False))
                tmp.replace(path)
            except (OSError, ValueError, TypeError):
                pass  # A read-only skill installation must still fetch data.
            finally:
                tmp.unlink(missing_ok=True)
        flight.set_result((deepcopy(value), meta))
        return value, meta
    except BaseException as exc:
        flight.set_exception(exc)
        raise
    finally:
        with _LOCK:
            _FLIGHTS.pop(key, None)
