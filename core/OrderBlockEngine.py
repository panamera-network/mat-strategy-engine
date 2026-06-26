from typing import Dict, List

from core.core_models import CandleSnapshot, OrderBlock


def detect_order_blocks(candles: List[CandleSnapshot], bos_events: List[Dict], timeframe: str = "") -> List[OrderBlock]:
    """Bullish OB = last bearish candle before a BOS Bullish.
    Bearish OB = last bullish candle before a BOS Bearish.

    `bos_events` is a list of {"type", "direction", "valid", "index"} dicts —
    "index" is the candle index (into `candles`) where the break happened.
    Only entries with type == "BOS" and valid == True produce an order block.
    """
    blocks: List[OrderBlock] = []

    for event in bos_events:
        if event.get("type") != "BOS" or not event.get("valid"):
            continue

        break_index = event.get("index")
        if break_index is None or break_index <= 0:
            continue

        direction = event.get("direction")
        ob_candle = None

        if direction == "Bullish":
            for i in range(break_index - 1, -1, -1):
                if candles[i].close < candles[i].open:
                    ob_candle = candles[i]
                    break
        elif direction == "Bearish":
            for i in range(break_index - 1, -1, -1):
                if candles[i].close > candles[i].open:
                    ob_candle = candles[i]
                    break

        if ob_candle is None:
            continue

        mitigated = _is_mitigated(ob_candle, candles[break_index + 1:])

        blocks.append(OrderBlock(
            type=direction,
            high=ob_candle.high,
            low=ob_candle.low,
            open=ob_candle.open,
            close=ob_candle.close,
            timeframe=timeframe,
            valid=not mitigated,
            mitigated=mitigated,
        ))

    return blocks


def _is_mitigated(ob_candle: CandleSnapshot, candles_after: List[CandleSnapshot]) -> bool:
    """An order block is mitigated once price revisits (closes back inside) its range."""
    return any(ob_candle.low <= c.close <= ob_candle.high for c in candles_after)
