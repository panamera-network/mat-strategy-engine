"""Pure swing/structure detection helpers — no dependency on other core/
engines, so both BiasEngine.py and StructureEngine.py can import this
without creating an import cycle (StructureEngine pulls in SuppressionEngine,
which pulls in BiasEngine)."""
from typing import Dict, List, Tuple

from core.core_models import CandleSnapshot, SNRLevel

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


def detect_structure_event(candles: List[CandleSnapshot], swing_highs: List[int], swing_lows: List[int]) -> Dict:
    """BOS = break in the direction of the existing trend (continuation).
    CHoCH = break against the existing trend (trend flip)."""
    if not swing_highs or not swing_lows:
        return {"type": "None", "direction": "Neutral", "valid": False, "index": len(candles) - 1}

    last_swing_high = candles[swing_highs[-1]].high
    last_swing_low = candles[swing_lows[-1]].low
    curr = candles[-1]
    trend = detect_trend(candles, swing_highs, swing_lows)
    break_index = len(candles) - 1

    if curr.close > last_swing_high:
        event_type = "CHOCH" if trend == "Bearish" else "BOS"
        return {"type": event_type, "direction": "Bullish", "valid": True, "index": break_index}

    if curr.close < last_swing_low:
        event_type = "CHOCH" if trend == "Bullish" else "BOS"
        return {"type": event_type, "direction": "Bearish", "valid": True, "index": break_index}

    return {"type": "None", "direction": "Neutral", "valid": False, "index": break_index}


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


def detect_snd(prev: CandleSnapshot, curr: CandleSnapshot) -> Dict:
    """Supply/demand zone tagging — kept simple for context_zone/context_level.
    See core/demand_engine.py for the ATR-based supply/demand engine."""
    range_prev = prev.high - prev.low
    range_curr = curr.high - curr.low

    if range_prev < range_curr * 0.5:
        if curr.close > curr.open and curr.low > prev.low:
            return {"type": "demand", "level": prev.low}
        elif curr.close < curr.open and curr.high < prev.high:
            return {"type": "supply", "level": prev.high}

    return {"type": "neutral", "level": None}
