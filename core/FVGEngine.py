from typing import List

from core.core_models import CandleSnapshot, FVG


def detect_fvg(candles: List[CandleSnapshot], timeframe: str = "") -> List[FVG]:
    """3-candle Fair Value Gap detection.

    Bullish FVG: candle[i+1].low > candle[i-1].high (gap between candle i-1's
    high and candle i+1's low, candle i is the impulse candle in the middle).
    Bearish FVG: candle[i+1].high < candle[i-1].low.

    Returns only unmitigated FVGs — a gap is mitigated once price trades back
    into it (any later candle's range overlaps the gap).
    """
    fvgs: List[FVG] = []

    for i in range(1, len(candles) - 1):
        prev_c = candles[i - 1]
        next_c = candles[i + 1]

        if next_c.low > prev_c.high:
            top, bottom = next_c.low, prev_c.high
            if not _is_mitigated(top, bottom, candles[i + 2:]):
                fvgs.append(FVG(type="Bullish", top=top, bottom=bottom, timeframe=timeframe))

        elif next_c.high < prev_c.low:
            top, bottom = prev_c.low, next_c.high
            if not _is_mitigated(top, bottom, candles[i + 2:]):
                fvgs.append(FVG(type="Bearish", top=top, bottom=bottom, timeframe=timeframe))

    return fvgs


def _is_mitigated(top: float, bottom: float, candles_after: List[CandleSnapshot]) -> bool:
    return any(c.low <= top and c.high >= bottom for c in candles_after)
