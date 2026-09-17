from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, strategy_momentum_confidence

# Fix #7AD — MAT PO3 (Power of Three) v1 baseline confidence formula,
# reported explicitly per this fix's own requirement (same "confirmed
# sequence, momentum supports only" pattern already established by Fix
# #7P/.../#7AB/#7AC):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5

_DIRECTION_MAP = {"Bullish": "long", "Bearish": "short"}


class PO3Strategy(Strategy):
    """Fix #7AD — MAT PO3 (Power of Three) v1: Balance candidate ->
    Manipulation -> Reclaim -> Distribution Confirmation. This strategy
    only reads pre-computed evidence from core.PO3Engine.detect_po3_
    sequence() -- see that module's own docstring for the full audit,
    locked rules, and lifecycle/stale-identity handling; this class never
    recomputes PO3 geometry or replays the Balance Range itself.

    LOCKED MAT RULES:
      - Fires ONLY when po3_stage == "confirmed" (never on "candidate"/
        "manipulation"/"reclaimed" -- those are structure-layer evidence
        only, never tradeable, per this fix's own explicit requirement).
      - SEQUENCE-SELECTION / FRESHNESS: detect_po3_sequence() may report
        a "confirmed" PO3 whose Distribution happened several candles
        ago (it reports genuine evidence regardless of age). This
        strategy fires ONLY when the current/latest candle IS the
        Distribution confirmation event -- checked via the existing
        Fix #7K `recent_candles` evidence (its last entry's own absolute
        index, straight copy, no new field invented) matching po3_
        distribution_index exactly, per this fix's own explicit
        instruction.
      - NOT gated on BOS, CHoCH, FVG, displacement, wick size,
        sustained-closes count, ATR magnitude, session/kill-zone timing
        (LOCKED RULE, same as PO3Engine's own detector). Momentum only
        ever SUPPORTS confidence below, never gates whether this
        strategy fires at all.

    Exactly 4 markings, all built from real, already-computed evidence --
    no fabricated geometry: the Balance Range itself (a `range` marking
    reusing the canonical BalanceRangeEngine geometry PO3Engine replayed,
    never redrawn), the Manipulation candle, the Reclaim candle, and the
    Distribution confirmation candle."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if snapshot.po3_stage != "confirmed":
            return None

        direction = _DIRECTION_MAP.get(snapshot.po3_direction)
        if direction is None:
            return None

        required = (
            snapshot.po3_range_start_index, snapshot.po3_range_start_timestamp,
            snapshot.po3_range_end_index, snapshot.po3_range_end_timestamp,
            snapshot.po3_range_high, snapshot.po3_range_low,
            snapshot.po3_manipulation_index, snapshot.po3_manipulation_timestamp,
            snapshot.po3_reclaim_index, snapshot.po3_reclaim_timestamp,
            snapshot.po3_distribution_index, snapshot.po3_distribution_timestamp, snapshot.po3_distribution_close,
        )
        if any(value is None for value in required):
            return None

        # Freshness gate -- see this class's own docstring. recent_candles
        # (Fix #7K) is always populated with real, absolute-indexed
        # entries by the time a PO3 could plausibly confirm (it needs a
        # confirmed Balance Range plus Manipulation plus Reclaim plus
        # Distribution -- far more candles than recent_candles' own
        # default count=3 window).
        recent_candles = snapshot.recent_candles or []
        if not recent_candles or recent_candles[-1].get("index") != snapshot.po3_distribution_index:
            return None

        reason = f"PO3 {snapshot.po3_direction} Distribution Confirmed"

        confidence = round(
            min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction), 1.0),
            2,
        )

        evidence_ref = {
            "source": "po3",
            "hypothesis_direction": snapshot.po3_hypothesis_direction,
            "range_high": snapshot.po3_range_high,
            "range_low": snapshot.po3_range_low,
            "manipulation_open": snapshot.po3_manipulation_open,
            "manipulation_high": snapshot.po3_manipulation_high,
            "manipulation_low": snapshot.po3_manipulation_low,
            "manipulation_close": snapshot.po3_manipulation_close,
            "reclaim_open": snapshot.po3_reclaim_open,
            "reclaim_high": snapshot.po3_reclaim_high,
            "reclaim_low": snapshot.po3_reclaim_low,
            "reclaim_close": snapshot.po3_reclaim_close,
            "distribution_open": snapshot.po3_distribution_open,
            "distribution_high": snapshot.po3_distribution_high,
            "distribution_low": snapshot.po3_distribution_low,
            "distribution_close": snapshot.po3_distribution_close,
        }

        range_marking = make_chart_marking(
            "range",
            type(self).__name__,
            snapshot.timeframe,
            "PO3 Balance Range",
            direction=direction,
            top=snapshot.po3_range_high,
            bottom=snapshot.po3_range_low,
            start_timestamp=snapshot.po3_range_start_timestamp,
            end_timestamp=snapshot.po3_range_end_timestamp,
            start_index=snapshot.po3_range_start_index,
            end_index=snapshot.po3_range_end_index,
            evidence_ref=evidence_ref,
        )
        manipulation_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "PO3 Manipulation",
            direction=direction,
            timestamp=snapshot.po3_manipulation_timestamp,
            candle_index=snapshot.po3_manipulation_index,
            evidence_ref=evidence_ref,
        )
        reclaim_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "PO3 Reclaim",
            direction=direction,
            timestamp=snapshot.po3_reclaim_timestamp,
            candle_index=snapshot.po3_reclaim_index,
            evidence_ref=evidence_ref,
        )
        distribution_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "PO3 Distribution Confirmation",
            direction=direction,
            timestamp=snapshot.po3_distribution_timestamp,
            candle_index=snapshot.po3_distribution_index,
            evidence_ref=evidence_ref,
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": reason,
            "confidence": confidence,
            "trigger": "PO3_DISTRIBUTION_CONFIRMED",
            "timestamp": snapshot.timestamp,
            "price": snapshot.po3_distribution_close,
            "chart_markings": [range_marking, manipulation_marking, reclaim_marking, distribution_marking],
        }
