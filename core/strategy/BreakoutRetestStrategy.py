from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, strategy_momentum_confidence

# Fix #7P — Breakout + Retest v1 baseline confidence formula, reported
# explicitly per this fix's own requirement (no new core formula, only
# canonical ingredients already on StrategySnapshot -- same base+weight
# shape already used by StructureReversalStrategy, Fix #7H):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
#
# BASE_CONFIDENCE (0.5) reflects the confirmed canonical evidence itself
# -- both a valid BOS breakout AND a later genuine retest (Fix #7P's own
# detect_breakout_retest(), which already requires the retest candle to
# CLOSE back on the held side -- a failed/wrong-side touch never sets
# retest_confirmed=True in the first place, so eligibility here already
# encodes "the level held"). MOMENTUM_WEIGHT (0.5) scales the canonical,
# direction-agreement-gated strategy_momentum_confidence() (Fix #6AU) on
# top of that base -- support evidence only, never gates eligibility.
# Range: exactly [0.5, 1.0] whenever eligible. No bias/zone scoring.
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5


class BreakoutRetestStrategy(Strategy):
    """Fix #7P — Breakout + Retest v1: a valid BOS breakout whose broken
    level was later genuinely retested (touched again and held), using
    Fix #7P's own detect_breakout_retest() evidence
    (breakout_origin_index/timestamp, retest_index/timestamp,
    retest_confirmed) -- never StructureSnapshot.event_index/
    event_timestamp, which always point at the current/most-recent
    candle and cannot by themselves prove a retest happened after the
    original break. No zone requirement, no bias gate, no raw momentum
    gate -- eligibility is breakout-plus-retest-only; momentum may only
    scale confidence once already eligible.

    v1 scope (Fix #7P's own audit conclusion, see
    structure_utils.detect_breakout_retest()'s docstring for the full
    reasoning): BOS only. CHoCH represents a trend FLIP -- the broken
    level is the origin of a brand new leg, not a continuation level
    being retested -- a materially different question not audited here.
    detect_breakout_retest() never populates retest evidence for a CHoCH
    event, and this strategy's own eligibility check independently
    requires structure_type == "BOS" too, as defense in depth against a
    hand-built or future-caller snapshot that sets retest_confirmed=True
    on a CHoCH event by mistake.
    """

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if not snapshot.structure_valid:
            return None
        if snapshot.structure_type != "BOS":
            return None
        if not snapshot.retest_confirmed:
            return None

        if snapshot.structure_direction == "Bullish":
            direction = "long"
            label = "Bullish Breakout + Retest"
        elif snapshot.structure_direction == "Bearish":
            direction = "short"
            label = "Bearish Breakout + Retest"
        else:
            return None

        if (
            snapshot.event_broken_level is None
            or snapshot.breakout_origin_index is None
            or snapshot.retest_index is None
        ):
            # Defensive: retest_confirmed=True should never appear without
            # this geometry (detect_breakout_retest() only ever sets them
            # together), but never fabricate a marking if it somehow does.
            return None
        if snapshot.retest_index <= snapshot.breakout_origin_index:
            # Defensive: a genuine retest must be strictly after the
            # breakout candle, never on it or before it. Never trusts
            # retest_confirmed alone without this ordering check.
            return None

        momentum_term = strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction)
        confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * momentum_term, 1.0), 2)

        breakout_marking = make_chart_marking(
            "structure",
            type(self).__name__,
            snapshot.timeframe,
            f"{label} (Breakout)",
            direction=direction,
            price=snapshot.event_broken_level,
            timestamp=snapshot.breakout_origin_timestamp,
            candle_index=snapshot.breakout_origin_index,
            evidence_ref={
                "source": "structure_events",
                "timeframe": snapshot.timeframe,
                "index": snapshot.breakout_origin_index,
            },
        )

        retest_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            f"{label} (Retest)",
            direction=direction,
            timestamp=snapshot.retest_timestamp,
            candle_index=snapshot.retest_index,
            evidence_ref={
                "source": "structure_events",
                "timeframe": snapshot.timeframe,
                "index": snapshot.retest_index,
            },
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "BOS_RETEST",
            "timestamp": snapshot.timestamp,
            "price": snapshot.event_broken_level,
            "chart_markings": [breakout_marking, retest_marking],
        }
