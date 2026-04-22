from __future__ import annotations

import hashlib
import time
from typing import Any


class TTLCache:
    def __init__(self, default_ttl: int = 300):
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = default_ttl

    def _make_key(self, *parts: str) -> str:
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, *parts: str) -> Any | None:
        key = self._make_key(*parts)
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, value: Any, *parts: str, ttl: int | None = None) -> None:
        key = self._make_key(*parts)
        self._store[key] = (time.monotonic() + (ttl or self._ttl), value)

    def clear(self) -> None:
        self._store.clear()

    def evict_expired(self) -> int:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        return len(expired)


cache = TTLCache()
