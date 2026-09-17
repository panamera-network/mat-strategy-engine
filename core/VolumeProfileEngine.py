"""Fix #7X — canonical Volume Profile foundation.

DATA/EVIDENCE AUDIT (performed before writing anything below):

  - No tick-fetching exists anywhere in this codebase -- `mt5.copy_ticks_
    range()`/`copy_ticks_from()` are never called (mt5/fetcher.py only
    ever calls `mt5.copy_rates_from_pos()`, OHLC + `tick_volume`). Adding
    one would be a genuinely NEW capability: unbounded per-symbol tick
    volume for a full trading week is potentially hundreds of thousands of
    rows, with no existing chunking/caching infrastructure for it.
  - `real_volume` is already confirmed 0 for every symbol on this
    account's broker feed (Fix #7R's own live 36-symbol audit,
    core/core_models.py's CandleDirection docstring) -- this account's
    feed carries no genuine exchange-reported traded size at all, at any
    granularity. Even genuine historical ticks from this feed would only
    ever carry a quote-count proxy (how many price updates arrived), the
    SAME underlying limitation `tick_volume` already has, just at finer
    resolution -- not a qualitatively different, more truthful signal.
  - Conclusion: Volume Profile does NOT fundamentally require a new tick
    fetch here -- the marginal resolution gain does not justify an
    unbounded new per-symbol fetch when the underlying activity signal is
    the same proxy either way. This foundation builds ONLY a candle-level
    APPROXIMATION (each M30 candle's tick_volume distributed across the
    price bins its [low, high] wick range overlaps, weighted by overlap
    fraction) -- explicitly labelled source_type="candle_approximation",
    never "tick_activity". A future fix could add genuine tick fetching
    IF a broker/feed with real traded-size ticks is ever used; nothing
    here should be read as proof that would be worthwhile on THIS feed.

  - Timestamp audit: MT5 candle `time` is broker-server time encoded as a
    raw Unix epoch, NOT genuine UTC. A live check against this account
    (Weltrade-Real) found `datetime.utcfromtimestamp(candle.time)` reads
    exactly 3 hours ahead of true `datetime.now(timezone.utc)` at the same
    instant -- the broker server runs UTC+3, with no correction applied
    anywhere in this codebase (every existing engine already treats these
    epochs as an opaque, self-consistent ordering, never converting to
    true UTC). Week-boundary detection below follows that SAME existing
    convention: ISO calendar weeks (Monday-Sunday) are computed directly
    off `datetime.utcfromtimestamp(candle.timestamp)` in this broker-time
    reference frame -- self-consistent (every candle uses the same
    reference), never claimed to be true UTC. This is safe specifically
    because only RELATIVE week grouping matters here (which candles share
    a trading week), not an absolute wall-clock alignment to a real-world
    UTC Monday.
"""
from collections import OrderedDict
from datetime import datetime
from typing import Dict, List, Optional

from core.CandleEngine import CandleEngine
from core.core_models import CandleSnapshot, VolumeProfile, VolumeProfileBin
from core.strategy.chart_markings import make_chart_marking

# Fix #7X — bin COUNT is fixed, bin WIDTH is derived from the profile's own
# observed [low, high] range -- this is what makes bin sizing instrument-
# aware without any fixed pip width or MT5 symbol-metadata lookup: a JPY
# pair (~150), a metal (~2000-4000), a crypto (~tens of thousands), and an
# FX major (~1.0-2.0) each get bins scaled to their OWN price range
# automatically. 24 bins over a week of M30 data (~240 candles for a
# 5-day FX/metal week) gives roughly 10 candles per bin on average --
# enough resolution for a weekly POC/VAH/VAL without being noisy.
NUM_BINS = 24

# Fix #7X — 70% is the standard, widely-used Volume Profile value-area
# convention (CME's own convention; the default in TradingView, NinjaTrader,
# ThinkorSwim, and most other Volume Profile implementations). No other
# percentage was silently chosen -- this is the audited, documented v1
# selection the task explicitly asked for.
VALUE_AREA_PCT = 0.70

# Fix #7X — bounded, explicit M30 fetch size for the previous-week lookup.
# 600 M30 candles is 12.5 days -- live-verified (EURUSD_i/XAUUSD_i/
# BTCUSD_i) to comfortably contain the current partial week plus a full
# previous week plus margin, for both weekend-closed (FX/metals) and
# continuously-traded (crypto) instruments. This is a DEDICATED fetch, not
# reused from the general per-request CandleCache: that cache is keyed by
# (symbol, tf) only and stores whatever count `fetch_all()` was called
# with (typically 100 for the rest of the engine) -- reusing it here would
# silently return only 100 candles (never enough for 2 trading weeks) with
# no error. See VolumeProfileEngine.get_previous_week_m30_profile()'s own
# docstring for why this fetch is therefore explicit and separate.
VP_FETCH_COUNT = 600

candle_engine = CandleEngine()


def build_volume_profile(
    candles: List[CandleSnapshot],
    symbol: str,
    timeframe: str,
    num_bins: int = NUM_BINS,
    value_area_pct: float = VALUE_AREA_PCT,
    source_type: str = "candle_approximation",
) -> Optional[VolumeProfile]:
    """Fix #7X — generic Volume Profile builder over ANY candle range. This
    is the ONE shared foundation V1 (previous-completed-week M30), V2
    (Fix #7Y's engine-detected Balance Range), and a future V3
    (user-selected manual range) must all build on -- the range itself is
    entirely the caller's choice (this function has no opinion on how
    `candles` was selected), only the profile MATH is shared.

    Distribution v1: each candle's own `volume` (tick_volume, per this
    module's own audit -- never real/traded volume) is split across every
    bin its [low, high] wick range overlaps, weighted by the fraction of
    the candle's own range inside that bin (overlap-length / candle
    range). This preserves total volume exactly (weights for one candle
    sum to 1.0) and is the standard approach used when genuine tick-by-
    tick prints aren't available -- it is explicitly NOT a claim that
    volume was evenly spread through the candle's life, only a documented
    approximation. A flat candle (high == low) contributes its full volume
    to the single bin its close falls in.

    POC is the midpoint price of the highest-volume bin. Value area
    (VAH/VAL) expands outward from the POC bin one bin at a time, always
    adding whichever adjacent side (next bin up vs next bin down) carries
    more volume, until cumulative volume reaches `value_area_pct` of the
    total (or the range is exhausted) -- the standard "expand from POC"
    convention, computed one bin at a time (not the alternate two-bin-pair
    TPO convention) as this v1's explicit, documented choice.

    Returns None for an empty `candles` list -- never fabricates a
    profile from no evidence."""
    if not candles:
        return None

    range_low = min(c.low for c in candles)
    range_high = max(c.high for c in candles)

    bins: List[VolumeProfileBin] = []
    if range_high <= range_low:
        # Degenerate: every candle in this range has identical low==high
        # (or a single candle) -- one bin covering the whole (zero-width)
        # range, all volume in it. Never divide by zero.
        total = sum(c.volume for c in candles)
        bins.append(VolumeProfileBin(price_low=range_low, price_high=range_high, volume=total))
        poc_price = range_low
        return VolumeProfile(
            symbol=symbol, timeframe=timeframe,
            range_start_timestamp=str(candles[0].timestamp),
            range_end_timestamp=str(candles[-1].timestamp),
            bins=bins, poc_price=poc_price,
            value_area_high=range_high, value_area_low=range_low,
            total_volume=total, value_area_pct=value_area_pct,
            num_bins=1, source_type=source_type,
        )

    bin_width = (range_high - range_low) / num_bins
    bins = [
        VolumeProfileBin(price_low=range_low + i * bin_width, price_high=range_low + (i + 1) * bin_width)
        for i in range(num_bins)
    ]

    for c in candles:
        c_range = c.high - c.low
        if c_range <= 0:
            idx = int((c.close - range_low) / bin_width)
            idx = max(0, min(num_bins - 1, idx))
            bins[idx].volume += c.volume
            continue
        for i, b in enumerate(bins):
            overlap = min(c.high, b.price_high) - max(c.low, b.price_low)
            if overlap > 0:
                bins[i].volume += c.volume * (overlap / c_range)

    total_volume = sum(b.volume for b in bins)
    poc_index = max(range(num_bins), key=lambda i: bins[i].volume)
    poc_price = (bins[poc_index].price_low + bins[poc_index].price_high) / 2

    low_idx = high_idx = poc_index
    cum = bins[poc_index].volume
    target = value_area_pct * total_volume if total_volume > 0 else 0.0
    while cum < target and (low_idx > 0 or high_idx < num_bins - 1):
        next_low_vol = bins[low_idx - 1].volume if low_idx > 0 else -1.0
        next_high_vol = bins[high_idx + 1].volume if high_idx < num_bins - 1 else -1.0
        if next_high_vol >= next_low_vol:
            high_idx += 1
            cum += bins[high_idx].volume
        else:
            low_idx -= 1
            cum += bins[low_idx].volume

    return VolumeProfile(
        symbol=symbol, timeframe=timeframe,
        range_start_timestamp=str(candles[0].timestamp),
        range_end_timestamp=str(candles[-1].timestamp),
        bins=bins, poc_price=poc_price,
        value_area_high=bins[high_idx].price_high,
        value_area_low=bins[low_idx].price_low,
        total_volume=total_volume, value_area_pct=value_area_pct,
        num_bins=num_bins, source_type=source_type,
    )


def get_previous_completed_week_candles(candles: List[CandleSnapshot]) -> List[CandleSnapshot]:
    """Fix #7X — pure function: groups already-fetched M30 `candles` by ISO
    calendar week (Monday-Sunday, computed via `datetime.utcfromtimestamp()`
    on this broker's own timestamp convention -- see this module's own
    docstring for the full timestamp audit) and returns exactly the
    candles belonging to the PREVIOUS completed week -- the second-most-
    recent distinct week found, never the most recent (which may still be
    forming). This never assumes Monday 00:00 of any particular real-world
    UTC date -- it only groups candles that already share a calendar week
    in whatever time reference their own timestamps use.

    Returns an empty list when fewer than 2 distinct weeks are present in
    `candles` (not enough history to know a prior week is genuinely
    complete) -- never a guess, never a partial/incomplete week mislabeled
    as complete."""
    if not candles:
        return []

    weeks: "OrderedDict[tuple, List[CandleSnapshot]]" = OrderedDict()
    for c in candles:
        key = datetime.utcfromtimestamp(int(c.timestamp)).isocalendar()[:2]
        weeks.setdefault(key, []).append(c)

    ordered_keys = sorted(weeks.keys())
    if len(ordered_keys) < 2:
        return []

    previous_week_key = ordered_keys[-2]
    return weeks[previous_week_key]


def build_profile_marking(
    *,
    strategy: str,
    timeframe: str,
    label: str,
    poc: float,
    vah: float,
    val: float,
    source_type: str,
    total_volume: float,
    value_area_pct: float,
    range_type: str,
    range_high: float = None,
    range_low: float = None,
    range_start_timestamp: str = None,
    range_end_timestamp: str = None,
    start_index: int = None,
    end_index: int = None,
    direction: str = None,
) -> Dict:
    """Fix #7Y — reusable "profile" chart marking builder for ANY Volume
    Profile evidence (this fix's Balance Range, Fix #7X's previous-week
    profile, or a future Manual Range) -- one shared implementation via
    the canonical chart_markings.make_chart_marking() contract, not a
    second marking builder per VP variant.

    Takes plain scalars (never a whole VolumeProfile object) because
    Strategy plugins only ever see flattened scalar fields via
    StrategySnapshot (the established convention throughout this
    codebase -- engine-side dataclasses are never threaded through to the
    Strategy layer). `range_type` distinguishes which VP source this
    marking describes (e.g. "balance_range", a future "manual_range") --
    Fix #7X's own committed strategy is UNCHANGED by this addition and
    does not use this helper."""
    evidence_ref = {
        "source": "volume_profile",
        "range_type": range_type,
        "range_high": range_high,
        "range_low": range_low,
        "source_type": source_type,
        "total_volume": total_volume,
        "value_area_pct": value_area_pct,
    }
    return make_chart_marking(
        "profile", strategy, timeframe, label,
        direction=direction,
        price=poc, top=vah, bottom=val,
        start_timestamp=range_start_timestamp, end_timestamp=range_end_timestamp,
        start_index=start_index, end_index=end_index,
        evidence_ref=evidence_ref,
    )


class VolumeProfileEngine:
    """Fix #7X — orchestrates the explicit, bounded M30 fetch + previous-
    week range selection + profile build. Strategy plugins never call
    this directly and never touch MT5 themselves (per this fix's own
    instruction) -- core/Output/Output.py calls this ONCE per symbol and
    sets the result post-hoc onto every timeframe's StructureSnapshot for
    that symbol (the same pattern Fix #7C/#7S already use for bias/
    conviction), since the previous-week M30 profile is symbol-scoped, not
    tf-scoped."""

    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine

    def get_previous_week_m30_profile(self, symbol: str) -> Optional[VolumeProfile]:
        """Explicit, bounded M30 fetch (VP_FETCH_COUNT candles, no cache
        reuse -- see this module's own VP_FETCH_COUNT docstring for why
        the general per-request CandleCache's fixed count is unsuitable
        here). Returns None when no genuine previous-completed-week data
        is available (see get_previous_completed_week_candles())."""
        candles = self.candle_engine.get_snapshots(symbol, "M30", count=VP_FETCH_COUNT)
        previous_week_candles = get_previous_completed_week_candles(candles)
        if not previous_week_candles:
            return None
        return build_volume_profile(previous_week_candles, symbol=symbol, timeframe="M30")


# Shared singleton -- mirrors the module-level engine-instance pattern
# already established (core/StructureEngine.py's own `candle_engine`/
# `momentum_engine`), so callers import this instead of constructing their
# own (this class holds no per-request state, so a shared instance is safe
# -- unlike StrategyEngine's own enabled/disabled state).
volume_profile_engine = VolumeProfileEngine(candle_engine)
