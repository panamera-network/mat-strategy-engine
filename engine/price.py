
from engine.core_models import PriceSnapshot
from engine.log import log_error
from mt5.fetcher import fetch_candles


def fetch_latest_price_snapshot(symbol: str, tf: str) -> PriceSnapshot | None:
    candles = fetch_candles(symbol, tf)
    if not candles or len(candles) < 2:
        log_error(symbol, tf, "price snapshot", "not enough candles")
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
