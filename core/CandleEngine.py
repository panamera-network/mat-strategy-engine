from core.core_models import CandleSnapshot
from mt5.fetcher import fetch_candles


class CandleEngine:
    def get_snapshots(self, symbol: str, tf: str, count: int = 100, cache=None) -> list[CandleSnapshot]:
        """If `cache` (a CandleCache) is given, read from it instead of
        hitting MT5 — backward compatible, existing callers that don't pass
        a cache behave exactly as before."""
        if cache is not None:
            return cache.get(symbol, tf, count=count)

        raw = fetch_candles(symbol, tf, count) or []
        return [
            CandleSnapshot(
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                timestamp=c.time
            )
            for c in raw
        ]
