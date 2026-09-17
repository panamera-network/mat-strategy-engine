from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, strategy_momentum_confidence

# Fix #7AA — MAT Inside Bar v1 baseline confidence formula, reported
# explicitly per this fix's own requirement (same "confirmed sequence,
# momentum supports only" pattern already established by Fix #7P/#7S/
# #7T/#7W/#7X/#7Y): Mother direction is never scored (LOCKED RULE), and
# child-count/child-size scoring is deliberately deferred, not invented.
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5

_DIRECTION_MAP = {"Bullish": "long", "Bearish": "short"}


class InsideBarBreakoutStrategy(Strategy):
    """Fix #7AA — MAT Inside Bar v1: Mother Bar -> minimum 3 consecutive
    contained child candles -> body breakout. This is MAT's OWN Inside
    Bar definition, not the textbook one -- do not replace these rules
    with a generic Inside Bar pattern.

    LOCKED MAT RULES (this strategy only reads pre-computed evidence from
    structure_utils.detect_inside_bar_sequence() -- see that function's
    own docstring for the full evidence audit, child-close-semantics
    correction, and stale-Mother selection rule; this class never
    recomputes candle geometry itself, beyond a trivial min/max of two
    already-provided scalars for the Mother's own body, purely for
    marking geometry):
      - Mother direction (bullish/bearish color) is IRRELEVANT and is
        NEVER used to gate eligibility or score confidence -- a bearish
        Mother producing a bullish breakout is exactly as valid as a
        bullish Mother producing a bullish breakout (see this fix's own
        test suite for both combinations, plus a bullish Mother
        producing a BEARISH breakout).
      - Children are validated by CLOSE only: `mother_body_low <=
        child.close <= mother_body_high` (inclusive at the boundary,
        MAT's own rule -- corrected from an earlier, wrong wick-
        containment-against-Mother-high/low design). A child's wick may
        extend beyond the Mother's own high/low WITHOUT invalidating it
        -- Mother H/L plays NO role in child eligibility in this v1, it
        is display-only geometry for the Mother candle itself.
      - Breakout direction comes ONLY from the breakout candle's CLOSE
        relative to the Mother's BODY (max/min of mother open/close),
        STRICTLY outside it (equality still counts as a child, never a
        breakout) -- never the Mother's high/low. A breakout does not
        need to break the Mother's wick range at all; closing outside
        the Mother body while the breakout candle's own wick still sits
        inside (or even outside) the Mother's high/low is intentionally
        valid (LOCKED RULE) and is never replaced with textbook
        high/low breakout logic.
      - No false-breakout filter, no retest requirement, no second
        confirmation candle -- false-break loss handling belongs to a
        later Entry/Exit -> Stop Loss concern, not this strategy.

    ELIGIBILITY GATES: NONE beyond the sequence itself -- no zone, S&R,
    S&D, bias, structure, or momentum eligibility gate (LOCKED RULE).
    Momentum only ever SUPPORTS confidence below, never gates whether
    this strategy fires at all.

    Exactly 3 markings, all built from real, already-computed evidence --
    no fabricated geometry: (1) a `candle` marking for the Mother Bar
    itself (its own real high/low, display-only -- NOT the child-
    containment rule), (2) a `range` marking covering the child sequence,
    with top/bottom = the Mother's own BODY high/low (the genuine
    eligibility boundary, not Mother H/L), (3) a `candle` marking for the
    breakout candle, labelled "Bullish Inside-Bar Breakout" or "Bearish
    Inside-Bar Breakout"."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if not snapshot.inside_bar_confirmed:
            return None

        direction = _DIRECTION_MAP.get(snapshot.inside_bar_direction)
        if direction is None:
            return None

        required = (
            snapshot.inside_bar_mother_index, snapshot.inside_bar_mother_timestamp,
            snapshot.inside_bar_mother_high, snapshot.inside_bar_mother_low,
            snapshot.inside_bar_children_start_index, snapshot.inside_bar_children_end_index,
            snapshot.inside_bar_breakout_index, snapshot.inside_bar_breakout_timestamp,
        )
        if any(value is None for value in required):
            return None

        label = f"{snapshot.inside_bar_direction} Inside-Bar Breakout"

        confidence = round(
            min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction), 1.0),
            2,
        )

        # Trivial min/max of two already-provided scalars -- not a
        # recomputation of candle geometry, just deriving the Mother's
        # own body boundary for marking purposes (the genuine child/
        # breakout eligibility rule, per detect_inside_bar_sequence()'s
        # own MAT child-close semantics).
        mother_body_high = max(snapshot.inside_bar_mother_open, snapshot.inside_bar_mother_close)
        mother_body_low = min(snapshot.inside_bar_mother_open, snapshot.inside_bar_mother_close)

        evidence_ref = {
            "source": "inside_bar_breakout",
            "mother_open": snapshot.inside_bar_mother_open,
            "mother_high": snapshot.inside_bar_mother_high,
            "mother_low": snapshot.inside_bar_mother_low,
            "mother_close": snapshot.inside_bar_mother_close,
            "mother_body_high": mother_body_high,
            "mother_body_low": mother_body_low,
            "children_count": snapshot.inside_bar_children_count,
            "breakout_close": snapshot.inside_bar_breakout_close,
        }

        mother_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "Mother Bar",
            direction=direction,
            timestamp=snapshot.inside_bar_mother_timestamp,
            candle_index=snapshot.inside_bar_mother_index,
            evidence_ref=evidence_ref,
        )
        children_marking = make_chart_marking(
            "range",
            type(self).__name__,
            snapshot.timeframe,
            "Inside Bar Child Sequence",
            direction=direction,
            top=mother_body_high,
            bottom=mother_body_low,
            start_timestamp=snapshot.inside_bar_children_start_timestamp,
            end_timestamp=snapshot.inside_bar_children_end_timestamp,
            start_index=snapshot.inside_bar_children_start_index,
            end_index=snapshot.inside_bar_children_end_index,
            evidence_ref=evidence_ref,
        )
        breakout_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            timestamp=snapshot.inside_bar_breakout_timestamp,
            candle_index=snapshot.inside_bar_breakout_index,
            evidence_ref=evidence_ref,
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "INSIDE_BAR_BREAKOUT",
            "timestamp": snapshot.timestamp,
            "price": snapshot.inside_bar_breakout_close,
            "chart_markings": [mother_marking, children_marking, breakout_marking],
        }
