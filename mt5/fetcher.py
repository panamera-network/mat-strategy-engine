from datetime import datetime
from typing import List
import MetaTrader5 as mt5
from pydantic import BaseModel
from .init import ensure_mt5_ready
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
    try:
        ensure_mt5_ready()
    except RuntimeError:
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


def fetch_candles_range(symbol: str, timeframe: str, date_from: datetime, date_to: datetime) -> List[Candle]:
    """Fix #7Z — explicit, BOUNDED historical fetch for a user-selected
    date range (`mt5.copy_rates_range()`), distinct from fetch_candles()'s
    count-based `mt5.copy_rates_from_pos()`. Used only by the Manual Range
    Volume Profile path (core/ManualRangeVolumeProfile.py) -- never called
    from the live per-cycle pipeline, never wired into StructureEngine.

    date_from/date_to are plain `datetime` objects, interpreted by MT5 in
    this account's own broker-server-time reference -- the SAME
    convention already established for every other candle timestamp in
    this codebase (see core/VolumeProfileEngine.py's own timestamp
    audit): callers should build them via `datetime.utcfromtimestamp()`
    on a raw epoch value taken from this same pipeline's own candle
    timestamps (e.g. a prior /core/history response), never assumed to
    be genuine UTC."""
    try:
        ensure_mt5_ready()
    except RuntimeError:
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
    raw = mt5.copy_rates_range(resolved, tf, date_from, date_to)

    if raw is None or len(raw) == 0:
        print(f"⚠️ No candles for {resolved} @ {timeframe} in range {date_from}..{date_to}")
        return []

    return [
        Candle(
            time=row['time'],
            open=row['open'],
            high=row['high'],
            low=row['low'],
            close=row['close'],
            volume=row['tick_volume'],
        )
        for row in raw
    ]


def fetch_candles_from_anchor(symbol: str, timeframe: str, anchor: datetime, count: int) -> List[Candle]:
    """Fix #7Z (stable Manual Range identity follow-up) — explicit,
    BOUNDED fetch of `count` candles ending at/before a FIXED `anchor`
    datetime (`mt5.copy_rates_from()`), never "now". Live-verified: unlike
    `fetch_candles()`'s `copy_rates_from_pos(pos=0, count)` (always the
    `count` most recent candles as of the instant of the call -- silently
    drifts to different real candles as time passes and new candles
    close), `copy_rates_from(symbol, tf, anchor, count)` returns the same
    `count` candles ending at/before `anchor` regardless of when the call
    is made or how many newer candles have since closed. This is what
    makes an index-addressed Manual Range request provably stable: the
    SAME (anchor, start_index, end_index) always resolves to the SAME
    candles. Used only by the Manual Range Volume Profile's stable-
    reference index path (core/ManualRangeVolumeProfile.py) -- never
    called from the live per-cycle pipeline."""
    try:
        ensure_mt5_ready()
    except RuntimeError:
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
    raw = mt5.copy_rates_from(resolved, tf, anchor, count)

    if raw is None or len(raw) == 0:
        print(f"⚠️ No candles for {resolved} @ {timeframe} ending at {anchor}")
        return []

    return [
        Candle(
            time=row['time'],
            open=row['open'],
            high=row['high'],
            low=row['low'],
            close=row['close'],
            volume=row['tick_volume'],
        )
        for row in raw
    ]
