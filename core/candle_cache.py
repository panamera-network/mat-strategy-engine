import threading
from typing import Dict, List, Tuple

from core.CandleEngine import CandleEngine
from core.core_models import CandleSnapshot


class CandleCache:
    """Request-scoped candle cache — build once per /core/output call via
    fetch_all(), then every engine reads through get() instead of hitting
    MT5 again for the same (symbol, tf). Discard after the request; this is
    not a persistent cache.
    """

    def __init__(self, candle_engine: CandleEngine):
        self._candle_engine = candle_engine
        self._store: Dict[Tuple[str, str], List[CandleSnapshot]] = {}
        self._lock = threading.Lock()

    def fetch_all(self, symbols: List[str], timeframes: List[str], count: int = 100) -> None:
        """Batch-fetch every (symbol, tf) combo once. Call this at the start
        of a request, before any engine runs."""
        for symbol in symbols:
            for tf in timeframes:
                candles = self._candle_engine.get_snapshots(symbol, tf, count=count)
                with self._lock:
                    self._store[(symbol, tf)] = candles

    def get(self, symbol: str, tf: str, count: int = 100) -> List[CandleSnapshot]:
        with self._lock:
            candles = self._store.get((symbol, tf))

        if candles is None:
            # Not pre-fetched (symbol/tf outside the batch) — fetch directly
            # and cache it so a repeat call within this request doesn't hit
            # MT5 again.
            candles = self._candle_engine.get_snapshots(symbol, tf, count=count)
            with self._lock:
                self._store[(symbol, tf)] = candles

        if count < len(candles):
            return candles[-count:]
        return candles
