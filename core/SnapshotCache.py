from typing import Dict, Optional
from threading import Lock
import time

class SnapshotCache:
    def __init__(self):
        self._store: Dict[str, Dict[str, any]] = {}
        self._timestamps: Dict[str, float] = {}
        self._lock = Lock()

    def set(self, symbol: str, snapshot: Dict[str, any]):
        with self._lock:
            self._store[symbol] = snapshot
            self._timestamps[symbol] = time.time()

    def get(self, symbol: str) -> Optional[Dict[str, any]]:
        with self._lock:
            return self._store.get(symbol)

    def get_age(self, symbol: str) -> Optional[float]:
        with self._lock:
            ts = self._timestamps.get(symbol)
            return time.time() - ts if ts else None

    def clear(self, symbol: Optional[str] = None):
        with self._lock:
            if symbol:
                self._store.pop(symbol, None)
                self._timestamps.pop(symbol, None)
            else:
                self._store.clear()
                self._timestamps.clear()


# Shared singleton — import this instead of instantiating SnapshotCache() directly,
# otherwise callers end up with disconnected in-memory stores.
snapshot_cache = SnapshotCache()
