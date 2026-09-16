from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, strategy_momentum_confidence

# Fix #7V — Support/Resistance Reaction v1 baseline confidence formula,
# reported explicitly per this fix's own requirement (snr_strength is the
# canonical ingredient, reused verbatim -- never rescored/recalculated --
# canonical momentum may support only, no bias/structure/S&D scoring):
#
#   confidence = round(min(snapshot.snr_strength + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
#
# Audit: StrategyEngine._snr_context() (Fix #7J) computes snr_strength as
# `1.0 - distance/tolerance` where distance is the CURRENT candle's
# mid-price to the nearest S&R level and tolerance is a proximity band --
# a genuine, already-bounded [0,1] PROXIMITY score (1.0 exactly at the
# level, 0.0 at the edge of the tolerance band). It is not a "level
# strength"/touch-count/significance score, and it is not itself proof of
# a reaction -- but once eligibility here has ALREADY independently
# proven genuine wick interaction + a held close (see the class docstring
# for the full audit), reusing snr_strength as the base confidence is
# semantically sound: it says how PRECISE the touch was, unscaled,
# exactly as the canonical formula already produces it. MOMENTUM_WEIGHT
# (0.3) scales the canonical, direction-agreement-gated
# strategy_momentum_confidence() (Fix #6AU) on top of that base -- support
# only, never gates eligibility. Range: [0.0, 1.0] -- unlike other v1
# strategies in this series, there is no flat eligibility floor, because
# snr_strength itself can be 0.0 exactly at the tolerance boundary (a
# genuinely eligible but maximally imprecise touch); this is reported
# explicitly, not hidden behind an invented floor.
MOMENTUM_WEIGHT = 0.3


class SupportResistanceReactionStrategy(Strategy):
    """Fix #7V — Support/Resistance Reaction v1: a REACTION strategy, not
    "price near S&R". Reuses the committed, canonical Fix #7J SNR contract
    (StrategySnapshot.nearest_support/nearest_resistance/snr_context/
    snr_strength -- sourced from StructureSnapshot.snr_levels, Fix #2's
    swing-based S&R engine) as a first-pass gate, then independently
    proves genuine interaction and a held close using real current-candle
    geometry -- never assuming proximity alone is a reaction.

    Audit findings (committed canonical evidence vs ambient-only SNR WIP):
      - nearest_support/nearest_resistance are the nearest Support/
        Resistance level PRICE by distance to the current candle's
        mid-price -- raw numbers only, no interaction/touch/hold evidence
        of their own.
      - snr_context ("at_support"/"at_resistance"/...) already gates on a
        distance-vs-tolerance proximity band (tolerance = max(half the
        current candle's range, a small price-relative floor)) -- closer
        than a blind "nearest", but NOT the same as a genuine wick
        overlap: when the price-relative floor dominates (a very quiet
        candle), "at_support"/"at_resistance" can be true even though the
        candle's actual high/low never reached the level. This strategy
        therefore does NOT treat snr_context alone as proof of
        interaction -- it re-checks real wick overlap explicitly below.
      - snr_strength is a proximity score (see the confidence comment
        above), not a reaction-quality or level-significance score.
      - The committed SNRLevel dataclass (structure_utils.derive_snr_
        levels(), Fix #2) carries only type/level/source/valid -- NO
        historical tested/untested/touch-count field exists in committed
        code. The `status`/`touches`/`timestamp`/`label` fields visible on
        SNRLevel in an ambient-WIP working tree are NOT committed and are
        never read here.
      - StrategySnapshot had no current-candle CLOSE price at all before
        this fix (only current_high/current_low) -- current_close (Fix
        #7V's own minimal additive wiring, straight copy of the same
        already-fetched current candle) closes that one real gap.

    v1 reaction definition (simple real-candle geometry, not a new
    indicator): the current candle's wick overlaps the relevant level
    (current_low <= level <= current_high) AND the candle's CLOSE ends up
    on the favorable side of it (Support: close > level; Resistance:
    close < level, both strict -- closing exactly through or onto the
    level does not count as holding). No zone/S&D dependency anywhere.

    Role identity is fixed and never swapped in v1: a Support reaction can
    only produce "long"; a Resistance reaction can only produce "short".
    A close cleanly through the level rejects outright -- role reversal
    (the level flipping identity) is explicitly deferred to a future
    strategy, not implemented here."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if snapshot.current_high is None or snapshot.current_low is None or snapshot.current_close is None:
            return None

        if snapshot.snr_context == "at_support":
            level = snapshot.nearest_support
            if level is None:
                return None
            touches = snapshot.current_low <= level <= snapshot.current_high
            holds = snapshot.current_close > level
            if not (touches and holds):
                return None
            direction = "long"
            level_type = "Support"
            label = "Support Reaction"
        elif snapshot.snr_context == "at_resistance":
            level = snapshot.nearest_resistance
            if level is None:
                return None
            touches = snapshot.current_low <= level <= snapshot.current_high
            holds = snapshot.current_close < level
            if not (touches and holds):
                return None
            direction = "short"
            level_type = "Resistance"
            label = "Resistance Reaction"
        else:
            return None

        if not snapshot.recent_candles:
            return None
        current_candle = snapshot.recent_candles[-1]

        confidence = round(
            min(snapshot.snr_strength + MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction), 1.0),
            2,
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
                "source": "support_resistance_reaction",
                "level_type": level_type,
                "level_price": level,
                "touches": touches,
                "holds": holds,
            },
        )
        candle_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            timestamp=current_candle.get("timestamp"),
            candle_index=current_candle.get("index"),
            evidence_ref={
                "source": "support_resistance_reaction",
                "level_type": level_type,
                "snr_strength": snapshot.snr_strength,
            },
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "SUPPORT_RESISTANCE_REACTION",
            "timestamp": snapshot.timestamp,
            "price": level,
            "chart_markings": [level_marking, candle_marking],
        }
