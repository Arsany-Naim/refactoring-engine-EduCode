"""Thread-safe in-memory session store with TTL eviction."""

import os
import threading
import time
from typing import Any


class SessionStore:
    def __init__(self, ttl_seconds: int = 7200, cleanup_interval_seconds: int = 60):
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._cleanup_interval_seconds = max(1, int(cleanup_interval_seconds))
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.RLock()

        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="SessionStoreCleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    def save(self, key: str, value: Any):
        expires_at = time.time() + self._ttl_seconds
        with self._lock:
            self._store[key] = (value, expires_at)

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None

            value, expires_at = entry
            if expires_at <= time.time():
                self._store.pop(key, None)
                return None
            return value

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def count(self) -> int:
        self._purge_expired()
        with self._lock:
            return len(self._store)

    def _cleanup_loop(self):
        while True:
            time.sleep(self._cleanup_interval_seconds)
            self._purge_expired()

    def _purge_expired(self):
        now = time.time()
        with self._lock:
            expired_keys = [
                key for key, (_, expires_at) in self._store.items() if expires_at <= now
            ]
            for key in expired_keys:
                self._store.pop(key, None)


def _read_ttl_seconds() -> int:
    raw = os.getenv("SESSION_STORE_TTL", "7200")
    try:
        return int(raw)
    except ValueError:
        return 7200


session_store = SessionStore(ttl_seconds=_read_ttl_seconds())
