from core.core_models import CandleSnapshot
from mt5.fetcher import fetch_candles


class CandleEngine:
    def get_snapshots(self, symbol: str, tf: str, count: int = 100) -> list[CandleSnapshot]:
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
