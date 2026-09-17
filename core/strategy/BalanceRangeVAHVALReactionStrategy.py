from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, strategy_momentum_confidence
from core.VolumeProfileEngine import build_profile_marking

# Fix #7Y — Balance Range Volume Profile VAH/VAL Reaction v1 baseline
# confidence formula, reported explicitly per this fix's own requirement
# (same reasoning as Fix #7X's own confidence audit -- no proximity-style
# ingredient exists for this evidence either). Unchanged by the naming
# rename (this class/file were originally "AccumulationRangeVAHVAL...";
# see core.BalanceRangeEngine's own module docstring for the rename
# rationale — same calculation, same thresholds):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5


class BalanceRangeVAHVALReactionStrategy(Strategy):
    """Fix #7Y — Balance Range Volume Profile VAH/VAL Reaction v1: the
    current candle genuinely touches (wick overlap) the detected Balance
    Range's Value Area High or Value Area Low and CLOSES back on the
    favorable side -- the SAME touch-and-hold reaction geometry Fix
    #7V/#7X already established, reused unchanged here for a different
    Volume Profile SOURCE (an engine-detected current-timeframe range
    instead of the previous completed week).

    v1 rule selection (this fix's own audit, reported before
    implementation): of the four candidates audited (VAH rejection, VAL
    rejection, POC reclaim/rejection, breakout-then-profile-relationship),
    this v1 implements ONLY the VAH/VAL reaction -- symmetric, one
    strategy, matching Fix #7X's own precedent exactly. POC reclaim/
    rejection is a materially different, more complex idea (implies an
    earlier cross) and stays deferred. A breakout-then-relationship rule
    would also contradict this fix's own range-identity design: the range
    is anchored at "now" (N-1, per the temporal-integrity fix) and expands
    backward (core.BalanceRangeEngine), so a signal only ever fires while
    the range is STILL the active candidate -- there is no "the range
    broke, now check the aftermath" state to react to in this v1 at all.

    Naming discipline: nothing here or upstream can distinguish genuine
    accumulation from distribution from generic sideways chop (see
    core.BalanceRangeEngine's own module docstring for the full audit) --
    this strategy's `reason` text says "Balance Range", never
    "Accumulation" (this class/file were renamed from
    "AccumulationRangeVAHVALReactionStrategy" for exactly this reason),
    and never implies confirmed smart-money intent. A future PO3 strategy
    may consume the SAME canonical Balance Range evidence and re-label it
    "PO3 Accumulation" only once Manipulation and Distribution are
    independently proven elsewhere -- this strategy makes no such claim.

    Exactly 2 markings: one `profile` marking (the whole detected range --
    start/end, range high/low, POC, VAH, VAL, via the shared
    build_profile_marking() foundation helper, Fix #7Y's own addition,
    range_type="balance_range") and one `level` marking for the specific
    VAH/VAL price actually touched -- not a third marking, per this fix's
    own "mark only the candle/level actually used for eligibility"
    instruction."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if not snapshot.balance_range_confirmed:
            return None
        if snapshot.balance_range_vah is None or snapshot.balance_range_val is None:
            return None
        if snapshot.current_high is None or snapshot.current_low is None or snapshot.current_close is None:
            return None
        if not snapshot.recent_candles:
            return None

        vah = snapshot.balance_range_vah
        val = snapshot.balance_range_val

        touches_vah = snapshot.current_low <= vah <= snapshot.current_high
        touches_val = snapshot.current_low <= val <= snapshot.current_high
        holds_below_vah = snapshot.current_close < vah
        holds_above_val = snapshot.current_close > val

        if touches_vah and holds_below_vah:
            level = vah
            level_type = "VAH"
            direction = "short"
            label = "Balance Range VAH Reaction"
        elif touches_val and holds_above_val:
            level = val
            level_type = "VAL"
            direction = "long"
            label = "Balance Range VAL Reaction"
        else:
            return None

        current_candle = snapshot.recent_candles[-1]

        confidence = round(
            min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction), 1.0),
            2,
        )

        profile_marking = build_profile_marking(
            strategy=type(self).__name__,
            timeframe=snapshot.timeframe,
            label=label,
            poc=snapshot.balance_range_poc,
            vah=vah,
            val=val,
            source_type=snapshot.balance_range_source_type,
            total_volume=snapshot.balance_range_total_volume,
            value_area_pct=snapshot.balance_range_value_area_pct,
            range_type="balance_range",
            range_high=snapshot.balance_range_high,
            range_low=snapshot.balance_range_low,
            range_start_timestamp=snapshot.balance_range_start_timestamp,
            range_end_timestamp=snapshot.balance_range_end_timestamp,
            start_index=snapshot.balance_range_start_index,
            end_index=snapshot.balance_range_end_index,
            direction=direction,
        )

        level_marking = make_chart_marking(
            "level",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            price=level,
            timestamp=current_candle.get("timestamp"),
            candle_index=current_candle.get("index"),
            evidence_ref={
                "source": "balance_range_reaction",
                "level_type": level_type,
                "level_price": level,
                "range_type": "balance_range",
            },
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "BALANCE_RANGE_VAH_VAL_REACTION",
            "timestamp": snapshot.timestamp,
            "price": level,
            "chart_markings": [profile_marking, level_marking],
        }
