from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, strategy_momentum_confidence

# Fix #7X — Volume Profile Weekly VAH/VAL Reaction v1 baseline confidence
# formula, reported explicitly per this fix's own requirement:
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
#
# No proximity-style ingredient (e.g. an SNR-strength equivalent) exists
# for Volume Profile evidence in this fix -- volume_profile_total_volume/
# num_bins describe the PROFILE's own construction, not how precisely the
# current candle touched VAH/VAL, so there is nothing analogous to reuse
# here (unlike Fix #7V's snr_strength). BASE_CONFIDENCE (0.5) reflects the
# confirmed reaction itself -- the same "confirmed evidence, momentum
# supports only" pattern already established by Fix #7P/#7S/#7T/#7W.
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5


class VolumeProfileWeeklyReactionStrategy(Strategy):
    """Fix #7X — Volume Profile (previous-completed-week M30) VAH/VAL
    Reaction v1: the current candle genuinely touches (wick overlap) the
    previous week's Value Area High or Value Area Low and CLOSES back on
    the favorable side -- the SAME reaction geometry Fix #7V already
    established for canonical S&R levels (touches = current_low <= level
    <= current_high; holds = a strict close on the favorable side),
    reused here unchanged for VP evidence instead of an SNR level.

    v1 rule selection (this fix's own audit, reported before
    implementation): three candidate VP reactions exist -- VAH reaction,
    VAL reaction, and POC interaction/reclaim/rejection. This v1
    implements ONLY the VAH/VAL reaction, treating VAH as resistance-like
    (a touch-and-hold-below produces "short") and VAL as support-like (a
    touch-and-hold-above produces "long") -- exactly mirroring Fix #7V's
    own Support/Resistance Reaction symmetry, one strategy covering both
    sides. POC interaction/reclaim/rejection is a materially different,
    more complex idea (reclaim implies an earlier cross, rejection implies
    a fade) and is deliberately DEFERRED to a future strategy -- not
    bundled into this one.

    volume_profile_source_type is always "candle_approximation" in this
    fix (see VolumeProfileEngine's own module docstring for the full data/
    evidence audit: no tick-fetching exists anywhere in this codebase, and
    this broker's tick/real volume fields carry no genuine traded size at
    any granularity) -- this strategy never claims to react to true
    traded-volume-by-price, only to a candle-level approximation of it.

    Exactly 2 markings: one `level` marking for the VAH/VAL price actually
    touched, one `candle` marking for the current reacting candle -- not
    the whole profile range/POC, since those are not part of THIS
    reaction's own evidence (see chart_markings' own "mark only what's
    actually used" convention, same as every other reaction strategy in
    this series)."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if snapshot.volume_profile_vah is None or snapshot.volume_profile_val is None:
            return None
        if snapshot.current_high is None or snapshot.current_low is None or snapshot.current_close is None:
            return None
        if not snapshot.recent_candles:
            return None

        vah = snapshot.volume_profile_vah
        val = snapshot.volume_profile_val

        touches_vah = snapshot.current_low <= vah <= snapshot.current_high
        touches_val = snapshot.current_low <= val <= snapshot.current_high
        holds_below_vah = snapshot.current_close < vah
        holds_above_val = snapshot.current_close > val

        if touches_vah and holds_below_vah:
            level = vah
            level_type = "VAH"
            direction = "short"
            label = "Previous-Week VAH Reaction"
        elif touches_val and holds_above_val:
            level = val
            level_type = "VAL"
            direction = "long"
            label = "Previous-Week VAL Reaction"
        else:
            return None

        current_candle = snapshot.recent_candles[-1]

        confidence = round(
            min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction), 1.0),
            2,
        )

        evidence_ref = {
            "source": "volume_profile_weekly_reaction",
            "level_type": level_type,
            "level_price": level,
            "volume_profile_source_type": snapshot.volume_profile_source_type,
            "volume_profile_range_start_timestamp": snapshot.volume_profile_range_start_timestamp,
            "volume_profile_range_end_timestamp": snapshot.volume_profile_range_end_timestamp,
        }

        level_marking = make_chart_marking(
            "level",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            price=level,
            timestamp=current_candle.get("timestamp"),
            candle_index=current_candle.get("index"),
            evidence_ref=evidence_ref,
        )
        candle_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            timestamp=current_candle.get("timestamp"),
            candle_index=current_candle.get("index"),
            evidence_ref=evidence_ref,
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "VOLUME_PROFILE_WEEKLY_REACTION",
            "timestamp": snapshot.timestamp,
            "price": level,
            "chart_markings": [level_marking, candle_marking],
        }
