from datetime import datetime
from typing import List
import MetaTrader5 as mt5
from pydantic import BaseModel
from .init import initialize_mt5
from .symbol_resolver import resolve_symbol
from .timeframes import resolve_timeframe

class Candle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float

def fetch_candles(symbol: str, timeframe: str, count: int = 100) -> List[Candle]:
    if not initialize_mt5():
        return []

    resolved = resolve_symbol(symbol)
    if not resolved:
        print(f"❌ Could not resolve symbol: {symbol}")
        return []

    info = mt5.symbol_info(resolved)
    if info is None:
        return []

    if not info.visible:
        mt5.symbol_select(resolved, True)

    tf = resolve_timeframe(timeframe)
    raw = mt5.copy_rates_from_pos(resolved, tf, 0, count)

    if raw is None or len(raw) == 0:
        print(f"⚠️ No candles for {resolved} @ {timeframe}")
        return []
        
    return [
        Candle(
            time=row['time'],
            open=row['open'],
            high=row['high'],
            low=row['low'],
            close=row['close'],
            volume=row['tick_volume'],
            source="mt5",
            symbol=resolved,
            timeframe=timeframe
        )

        for row in raw
    ]
