"""简单缓存"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class TTLCache:
    """带 TTL 的简单缓存"""
    def __init__(self, ttl: float = 300, maxsize: int = 128):
        self._ttl = ttl
        self._maxsize = maxsize
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, default=None):
        with self._lock:
            if key in self._data:
                ts, val = self._data[key]
                if time.time() - ts < self._ttl:
                    return val
                del self._data[key]
        return default

    def set(self, key: str, value):
        with self._lock:
            if len(self._data) >= self._maxsize:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                del self._data[oldest]
            self._data[key] = (time.time(), value)

    def clear(self):
        with self._lock:
            self._data.clear()
