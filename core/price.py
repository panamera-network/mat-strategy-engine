
from core.CandleEngine import CandleEngine
from core.core_models import PriceSnapshot
from core.log import log_error


def fetch_latest_price_snapshot(symbol: str, tf: str, candle_engine: CandleEngine) -> PriceSnapshot | None:
    candles = candle_engine.get_snapshots(symbol, tf, count=2)
    if len(candles) < 2:
        log_error(symbol, tf, "price snapshot", "not enough candle snapshots")
        return None

    prev, curr = candles[-2], candles[-1]
    return PriceSnapshot(
        symbol=symbol,
        timeframe=tf,
        high=curr.high,
        low=curr.low,
        prev_high=prev.high,
        prev_low=prev.low
    )

