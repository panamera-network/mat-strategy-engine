from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, strategy_momentum_confidence

# Fix #7AB — MAT Three Inside Up/Down v1 baseline confidence formula,
# reported explicitly per this fix's own requirement (same "confirmed
# sequence, momentum supports only" pattern already established by Fix
# #7P/#7S/#7T/#7W/#7X/#7Y/#7AA):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5

_DIRECTION_MAP = {"Bullish": "long", "Bearish": "short"}


class ThreeInsideStrategy(Strategy):
    """Fix #7AB — MAT Three Inside Up / Three Inside Down v1: a fixed,
    exactly-3-candle pattern (Candle1 -> Candle2 body-in-body containment
    -> Candle3 confirmation). This strategy only reads pre-computed
    evidence from structure_utils.detect_three_inside_sequence() -- see
    that function's own docstring for the full evidence audit and
    Fix #7AB's own rule-audit report for the complete textbook-vs-MAT
    comparison; this class never recomputes candle geometry itself.

    LOCKED MAT RULES:
      - Three Inside Up: C1 bearish, C2 bullish, C3 bullish, C3 closes
        STRICTLY above C1's OPEN (not C1's body high, and not C1's
        wick high -- specifically C1's open).
      - Three Inside Down: C1 bullish, C2 bearish, C3 bearish, C3 closes
        STRICTLY below C1's OPEN.
      - C2's body must be fully within C1's body, INCLUSIVE boundaries
        -- but C2's WICK may extend beyond C1's high/low without
        invalidating the pattern (mirrors Fix #7AA's own final
        wick-doesn't-matter conclusion).
      - A doji (close == open) at ANY of C1/C2/C3 rejects the whole
        sequence outright -- every position requires real directional
        color.
      - NO prior-trend eligibility gate, NO gap requirement, NO
        Candle-1 ATR/significance threshold, and NO zone/S&R/S&D/bias/
        structure/momentum eligibility gate of any kind (LOCKED RULE).
        Momentum only ever SUPPORTS confidence below, never gates
        whether this strategy fires at all.

    Exactly 3 markings, all built from real, already-computed evidence --
    no fabricated geometry: one `candle` marking each for C1, C2, and C3,
    showing the actual three candles the pattern was built from."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if not snapshot.three_inside_confirmed:
            return None

        direction = _DIRECTION_MAP.get(snapshot.three_inside_direction)
        if direction is None:
            return None

        required = (
            snapshot.three_inside_c1_index, snapshot.three_inside_c1_timestamp, snapshot.three_inside_c1_open,
            snapshot.three_inside_c2_index, snapshot.three_inside_c2_timestamp,
            snapshot.three_inside_c3_index, snapshot.three_inside_c3_timestamp, snapshot.three_inside_c3_close,
        )
        if any(value is None for value in required):
            return None

        reason = f"{snapshot.three_inside_direction} Three Inside"

        confidence = round(
            min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction), 1.0),
            2,
        )

        evidence_ref = {
            "source": "three_inside",
            "c1_open": snapshot.three_inside_c1_open,
            "c1_high": snapshot.three_inside_c1_high,
            "c1_low": snapshot.three_inside_c1_low,
            "c1_close": snapshot.three_inside_c1_close,
            "c2_open": snapshot.three_inside_c2_open,
            "c2_high": snapshot.three_inside_c2_high,
            "c2_low": snapshot.three_inside_c2_low,
            "c2_close": snapshot.three_inside_c2_close,
            "c3_open": snapshot.three_inside_c3_open,
            "c3_high": snapshot.three_inside_c3_high,
            "c3_low": snapshot.three_inside_c3_low,
            "c3_close": snapshot.three_inside_c3_close,
        }

        c1_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "Three Inside C1",
            direction=direction,
            timestamp=snapshot.three_inside_c1_timestamp,
            candle_index=snapshot.three_inside_c1_index,
            evidence_ref=evidence_ref,
        )
        c2_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "Three Inside C2",
            direction=direction,
            timestamp=snapshot.three_inside_c2_timestamp,
            candle_index=snapshot.three_inside_c2_index,
            evidence_ref=evidence_ref,
        )
        c3_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "Three Inside Confirmation",
            direction=direction,
            timestamp=snapshot.three_inside_c3_timestamp,
            candle_index=snapshot.three_inside_c3_index,
            evidence_ref=evidence_ref,
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": reason,
            "confidence": confidence,
            "trigger": "THREE_INSIDE",
            "timestamp": snapshot.timestamp,
            "price": snapshot.three_inside_c3_close,
            "chart_markings": [c1_marking, c2_marking, c3_marking],
        }
