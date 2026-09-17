from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, strategy_momentum_confidence

# Fix #7AC — MAT Three White Soldiers/Three Black Crows v1 baseline
# confidence formula, reported explicitly per this fix's own requirement
# (same "confirmed sequence, momentum supports only" pattern already
# established by Fix #7P/#7S/#7T/#7W/#7X/#7Y/#7AA/#7AB):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5

_DIRECTION_MAP = {"Bullish": "long", "Bearish": "short"}
_PATTERN_NAME = {"Bullish": "Three White Soldiers", "Bearish": "Three Black Crows"}


class ThreeSoldiersCrowsStrategy(Strategy):
    """Fix #7AC — MAT Three White Soldiers / Three Black Crows v1: a
    fixed, exactly-3-candle pattern (three same-color candles with
    progressively-extending closes, each opening inside the prior
    candle's real body). This strategy only reads pre-computed evidence
    from structure_utils.detect_three_soldiers_crows_sequence() -- see
    that function's own docstring for the full evidence audit and
    Fix #7AC's own rule-audit report for the complete textbook-vs-MAT
    comparison; this class never recomputes candle geometry itself.

    LOCKED MAT RULES:
      - Three White Soldiers: C1/C2/C3 all bullish, C2.close > C1.close,
        C3.close > C2.close, C2.open inside C1's body (inclusive), C3.
        open inside C2's body (inclusive).
      - Three Black Crows: C1/C2/C3 all bearish, C2.close < C1.close,
        C3.close < C2.close, C2.open inside C1's body (inclusive), C3.
        open inside C2's body (inclusive).
      - A doji (close == open) at ANY of C1/C2/C3 rejects the whole
        sequence outright -- every position requires real directional
        color.
      - NO prior high/low break requirement, NO small-wick threshold,
        NO long-body/ATR-relative-size threshold, NO body-size
        similar/increasing requirement, NO prior-trend eligibility gate,
        NO gap requirement, and NO zone/S&R/S&D/bias/structure
        eligibility gate of any kind (LOCKED RULE). Momentum only ever
        SUPPORTS confidence below, never gates whether this strategy
        fires at all.

    Exactly 3 markings, all built from real, already-computed evidence --
    no fabricated geometry: one `candle` marking each for C1, C2, and C3,
    showing the actual three candles the pattern was built from."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if not snapshot.three_soldiers_crows_confirmed:
            return None

        direction = _DIRECTION_MAP.get(snapshot.three_soldiers_crows_direction)
        if direction is None:
            return None

        required = (
            snapshot.three_soldiers_crows_c1_index, snapshot.three_soldiers_crows_c1_timestamp,
            snapshot.three_soldiers_crows_c2_index, snapshot.three_soldiers_crows_c2_timestamp,
            snapshot.three_soldiers_crows_c3_index, snapshot.three_soldiers_crows_c3_timestamp,
            snapshot.three_soldiers_crows_c3_close,
        )
        if any(value is None for value in required):
            return None

        reason = _PATTERN_NAME[snapshot.three_soldiers_crows_direction]

        confidence = round(
            min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction), 1.0),
            2,
        )

        evidence_ref = {
            "source": "three_soldiers_crows",
            "c1_open": snapshot.three_soldiers_crows_c1_open,
            "c1_high": snapshot.three_soldiers_crows_c1_high,
            "c1_low": snapshot.three_soldiers_crows_c1_low,
            "c1_close": snapshot.three_soldiers_crows_c1_close,
            "c2_open": snapshot.three_soldiers_crows_c2_open,
            "c2_high": snapshot.three_soldiers_crows_c2_high,
            "c2_low": snapshot.three_soldiers_crows_c2_low,
            "c2_close": snapshot.three_soldiers_crows_c2_close,
            "c3_open": snapshot.three_soldiers_crows_c3_open,
            "c3_high": snapshot.three_soldiers_crows_c3_high,
            "c3_low": snapshot.three_soldiers_crows_c3_low,
            "c3_close": snapshot.three_soldiers_crows_c3_close,
        }

        c1_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "Three Soldiers/Crows C1",
            direction=direction,
            timestamp=snapshot.three_soldiers_crows_c1_timestamp,
            candle_index=snapshot.three_soldiers_crows_c1_index,
            evidence_ref=evidence_ref,
        )
        c2_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "Three Soldiers/Crows C2",
            direction=direction,
            timestamp=snapshot.three_soldiers_crows_c2_timestamp,
            candle_index=snapshot.three_soldiers_crows_c2_index,
            evidence_ref=evidence_ref,
        )
        c3_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "Three Soldiers/Crows C3",
            direction=direction,
            timestamp=snapshot.three_soldiers_crows_c3_timestamp,
            candle_index=snapshot.three_soldiers_crows_c3_index,
            evidence_ref=evidence_ref,
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": reason,
            "confidence": confidence,
            "trigger": "THREE_SOLDIERS_CROWS",
            "timestamp": snapshot.timestamp,
            "price": snapshot.three_soldiers_crows_c3_close,
            "chart_markings": [c1_marking, c2_marking, c3_marking],
        }
