from datetime import datetime

from core.core_models import CandleSnapshot
from mt5.fetcher import fetch_candles, fetch_candles_from_anchor, fetch_candles_range


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

    def get_snapshots_by_range(self, symbol: str, tf: str, date_from: datetime, date_to: datetime) -> list[CandleSnapshot]:
        """Fix #7Z — explicit, bounded date-range fetch (mt5.copy_rates_
        range() via fetch_candles_range()), for the Manual Range Volume
        Profile path only. No `cache` param -- deliberately never routed
        through the shared per-request CandleCache (that cache is keyed
        by (symbol, tf) + a candle COUNT, not a date range, and is
        request-scoped/ephemeral; Manual Range has its own dedicated,
        indefinite in-process cache -- see core/ManualRangeVolumeProfile.py)."""
        raw = fetch_candles_range(symbol, tf, date_from, date_to) or []
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

    def get_snapshots_from_anchor(self, symbol: str, tf: str, anchor: datetime, count: int) -> list[CandleSnapshot]:
        """Fix #7Z (stable Manual Range identity follow-up) — `count`
        candles ending at/before a FIXED `anchor` datetime
        (mt5.copy_rates_from() via fetch_candles_from_anchor()), never
        "now". This is what makes the Manual Range stable-reference index
        path provably stable -- see fetch_candles_from_anchor()'s own
        docstring for the live-verified semantics. No `cache` param, same
        reasoning as get_snapshots_by_range() above."""
        raw = fetch_candles_from_anchor(symbol, tf, anchor, count) or []
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
