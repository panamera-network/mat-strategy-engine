"""Pure swing/structure detection helpers — no dependency on other core/
engines, so both BiasEngine.py and StructureEngine.py can import this
without creating an import cycle (StructureEngine pulls in SuppressionEngine,
which pulls in BiasEngine)."""
from typing import Dict, List, Tuple

from core.core_models import CandleSnapshot, SNRLevel, SwingPoint

SWING_LOOKBACK = 20
SWING_WINDOW = 3


def find_swings(candles: List[CandleSnapshot], window: int = SWING_WINDOW) -> Tuple[List[int], List[int]]:
    """Returns (swing_high_indices, swing_low_indices) into `candles`.

    A swing high at i needs candles[i].high higher than `window` candles on
    both sides; a swing low needs candles[i].low lower than `window` candles
    on both sides. The most recent `window` candles can never be confirmed
    swings yet (not enough candles to their right) — that's expected.
    """
    swing_highs: List[int] = []
    swing_lows: List[int] = []
    n = len(candles)

    for i in range(window, n - window):
        left = candles[i - window:i]
        right = candles[i + 1:i + 1 + window]

        if all(candles[i].high > c.high for c in left) and all(candles[i].high > c.high for c in right):
            swing_highs.append(i)

        if all(candles[i].low < c.low for c in left) and all(candles[i].low < c.low for c in right):
            swing_lows.append(i)

    return swing_highs, swing_lows


def detect_trend(candles: List[CandleSnapshot], swing_highs: List[int], swing_lows: List[int]) -> str:
    """Bullish = higher highs + higher lows. Bearish = lower highs + lower lows."""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "Neutral"

    higher_high = candles[swing_highs[-1]].high > candles[swing_highs[-2]].high
    higher_low = candles[swing_lows[-1]].low > candles[swing_lows[-2]].low
    lower_high = candles[swing_highs[-1]].high < candles[swing_highs[-2]].high
    lower_low = candles[swing_lows[-1]].low < candles[swing_lows[-2]].low

    if higher_high and higher_low:
        return "Bullish"
    if lower_high and lower_low:
        return "Bearish"
    return "Neutral"


def _last_swing_label(candles: List[CandleSnapshot], swing_indices: List[int], is_high: bool) -> str:
    """Fix #5F2 — labels the LAST entry of a swing index list, reusing the
    exact same adjacent-swing comparison label_swing_points() already
    applies to every swing point (and detect_trend() already applies to
    the same [-1] vs [-2] pair internally) — no new rule, no new formula."""
    latest = candles[swing_indices[-1]]
    if len(swing_indices) < 2:
        return "LH" if is_high else "HL"
    previous = candles[swing_indices[-2]]
    if is_high:
        return "HH" if latest.high > previous.high else "LH"
    return "LL" if latest.low < previous.low else "HL"


def detect_structure_event(candles: List[CandleSnapshot], swing_highs: List[int], swing_lows: List[int]) -> Dict:
    """BOS = break in the direction of the existing trend (continuation).
    CHoCH = break against the existing trend (trend flip).

    `broken_level` (Fix #2) is the actual swing high/low price that was
    breached — last_swing_high/last_swing_low below were already computed
    for the comparisons, just exposed on the return value now, not a new
    calculation and not a formula change.

    Fix #5F2 — leg_origin_* (additive, no detection-formula change): the
    latest confirmed OPPOSING swing — the one NOT broken — which was
    already being computed as last_swing_low/last_swing_high below purely
    for the break comparison itself. This is the structural leg's origin
    (the swing the leg that produced this break started from) — not a
    demand/supply zone origin (a different engine, a different, unrelated
    concept) and not a displacement-candle detector (a possible future,
    more expensive refinement, not this one). None when there's no
    confirmed event.

    Fix #6C — pre_break_trend (additive, no detection-formula change): the
    `trend` value already computed below, exposed as-is — the two-swing
    trend read BEFORE this break was evaluated, i.e. exactly what BOS/CHoCH
    was decided against (Fix #6B's audit). "Neutral" is a real, meaningful
    value here, not a missing-evidence placeholder: it means a break
    occurred while no two-swing trend was established either way, which is
    exactly the edge case where today's BOS label is a default/fallback
    rather than a substantiated continuation claim (see Fix #6B Q2) — a
    consumer that wants to tell that case apart from a "true" BOS needs
    this field. None only when there is no confirmed event at all (same
    convention as leg_origin_*/broken_level above) — pre_break_trend is
    scoped to an actual break, so there is no "pre-break" moment to report
    without one."""
    no_event = {
        "type": "None", "direction": "Neutral", "valid": False, "index": len(candles) - 1, "broken_level": None,
        "leg_origin_index": None, "leg_origin_timestamp": None, "leg_origin_price": None, "leg_origin_swing_label": None,
        "pre_break_trend": None,
    }
    if not swing_highs or not swing_lows:
        return no_event

    last_swing_high = candles[swing_highs[-1]].high
    last_swing_low = candles[swing_lows[-1]].low
    curr = candles[-1]
    trend = detect_trend(candles, swing_highs, swing_lows)
    break_index = len(candles) - 1

    if curr.close > last_swing_high:
        event_type = "CHOCH" if trend == "Bearish" else "BOS"
        origin_index = swing_lows[-1]
        return {
            "type": event_type, "direction": "Bullish", "valid": True, "index": break_index, "broken_level": last_swing_high,
            "leg_origin_index": origin_index,
            "leg_origin_timestamp": str(candles[origin_index].timestamp),
            "leg_origin_price": last_swing_low,
            "leg_origin_swing_label": _last_swing_label(candles, swing_lows, is_high=False),
            "pre_break_trend": trend,
        }

    if curr.close < last_swing_low:
        event_type = "CHOCH" if trend == "Bullish" else "BOS"
        origin_index = swing_highs[-1]
        return {
            "type": event_type, "direction": "Bearish", "valid": True, "index": break_index, "broken_level": last_swing_low,
            "leg_origin_index": origin_index,
            "leg_origin_timestamp": str(candles[origin_index].timestamp),
            "leg_origin_price": last_swing_high,
            "leg_origin_swing_label": _last_swing_label(candles, swing_highs, is_high=True),
            "pre_break_trend": trend,
        }

    return no_event


def label_swing_points(
    candles: List[CandleSnapshot],
    swing_highs: List[int],
    swing_lows: List[int],
) -> List[SwingPoint]:
    """HH/LH/LL/HL evidence for every confirmed swing point — price +
    index/timestamp. Independent of derive_snr_levels() below (which tags
    this same classification onto SNRLevel.source as a side effect of
    building resistance/support levels) so structure evidence doesn't
    require touching SNR level construction. Same classification rule,
    computed separately."""
    points: List[SwingPoint] = []

    for idx, swing_i in enumerate(swing_highs):
        label = "HH" if idx > 0 and candles[swing_i].high > candles[swing_highs[idx - 1]].high else "LH"
        points.append(SwingPoint(
            label=label,
            price=candles[swing_i].high,
            index=swing_i,
            timestamp=str(candles[swing_i].timestamp),
        ))

    for idx, swing_i in enumerate(swing_lows):
        label = "LL" if idx > 0 and candles[swing_i].low < candles[swing_lows[idx - 1]].low else "HL"
        points.append(SwingPoint(
            label=label,
            price=candles[swing_i].low,
            index=swing_i,
            timestamp=str(candles[swing_i].timestamp),
        ))

    points.sort(key=lambda p: p.index)
    return points


def derive_snr_levels(candles: List[CandleSnapshot], swing_highs: List[int], swing_lows: List[int], structure_event: Dict) -> List[SNRLevel]:
    levels: List[SNRLevel] = []

    for prev_i, cur_i in zip(swing_highs, swing_highs[1:]):
        if candles[cur_i].high > candles[prev_i].high:
            levels.append(SNRLevel(type="Resistance", level=candles[cur_i].high, source="HH"))

    for prev_i, cur_i in zip(swing_lows, swing_lows[1:]):
        if candles[cur_i].low < candles[prev_i].low:
            levels.append(SNRLevel(type="Support", level=candles[cur_i].low, source="LL"))

    levels.sort(key=lambda lvl: lvl.level)

    # Role reversal at the CHoCH point — the level nearest the break flips
    if structure_event.get("type") == "CHOCH" and levels:
        flip_target = min(levels, key=lambda lvl: abs(lvl.level - candles[-1].close))
        flip_target.type = "Support" if flip_target.type == "Resistance" else "Resistance"
        flip_target.source = "CHOCH_flip"

    return levels
