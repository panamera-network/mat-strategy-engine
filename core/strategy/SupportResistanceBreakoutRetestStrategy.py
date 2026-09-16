from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, strategy_momentum_confidence

# Fix #7W — Support/Resistance Breakout + Retest v1 baseline confidence
# formula, reported explicitly per this fix's own requirement:
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
#
# Audit: snapshot.snr_strength (Fix #7J's _snr_context()) is a proximity
# score computed against the CURRENT candle's mid-price and the CURRENT
# nearest level -- it has no historical replay capability and was never
# computed AT the retest candle's own moment. Reusing it here would
# silently repurpose a "how close is price right now" reading as "how
# clean was the retest that may have happened several candles ago", which
# cannot be proven from the committed evidence (same conclusion Fix #7V
# reached for its OWN, current-candle reaction -- and this fix's retest
# candle is frequently NOT the current candle at all). Per this fix's own
# instruction ("if that cannot be proven historically, do not use it"),
# snr_strength is deliberately NOT used. BASE_CONFIDENCE (0.5) reflects the
# confirmed breakout+retest sequence itself -- the same "confirmed
# sequence, momentum supports only" pattern already established by Fix
# #7P/#7S/#7T's confidence formulas. No bias/structure/S&D scoring.
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5

_DIRECTION_MAP = {"Bullish": "long", "Bearish": "short"}


class SupportResistanceBreakoutRetestStrategy(Strategy):
    """Fix #7W — Support/Resistance Breakout + Retest v1: a genuine
    breakout-then-later-retest ROLE FLIP strategy (Resistance -> Support,
    or Support -> Resistance), unlike Fix #7V's SupportResistanceReaction
    (same-role reaction, role reversal explicitly deferred there).

    Audit findings (before writing any new detection logic):
      - StrategyEngine._snr_context() (Fix #7J) only ever reports the
        CURRENT nearest support/resistance by proximity to "now" via
        nearest_support/nearest_resistance/snr_context/snr_strength -- it
        has no memory of whether a level was ever broken, nor of when. A
        single StrategySnapshot cannot, by itself, prove "this used to be
        Resistance, price broke above it, and later held above it as
        Support" -- only that some level is nearby right now. This is a
        real historical-evidence gap, the same class of gap Fix #7P/#7T/
        #7U each closed with a replay-based helper over the same already-
        fetched candle window -- not a case where the committed evidence
        was already sufficient.
      - Closed via structure_utils.detect_snr_role_flip() (new), which
        reuses the SAME already-derived StructureSnapshot.snr_levels list
        (Fix #2's canonical S&R engine, never redefined) and the SAME
        already-fetched lookback window -- no new fetch, no new S&R
        detection. It is deliberately NOT built on Fix #7P's
        detect_breakout_retest()/structure_event: a BOS/CHoCH's
        broken_level is a swing-based STRUCTURE level, a different concept
        from an S&R level, and this fix's instruction explicitly forbids
        reusing #7P's structure event as S&R evidence. Only the geometric
        ALGORITHM is reused -- _find_current_leg_origin() (already a
        single shared, structure-agnostic implementation) and the
        identical wick-overlap tolerance detect_breakout_retest() already
        established (max(candle_range * 0.25, abs(level) * 0.0003)) --
        applied to an S&R level's price instead of a structure break's.
      - Ordering (breakout_index < retest_index, same-candle rejected,
        stale-old-breakout immunity) is proven the same way Fix #7P/#7T
        already proved it: _find_current_leg_origin()'s backward scan for
        the START of the CURRENT unbroken run beyond the level naturally
        excludes any earlier, already-invalidated crossing of the same
        level, and the retest scan only ever looks strictly AFTER that
        origin and strictly BEFORE "now".
      - snr_strength is not reused for confidence -- see the module-level
        comment above for the full audit.

    Role reversal IS the point of this strategy (unlike Fix #7V):
    Resistance -> Support and Support -> Resistance are both valid
    outcomes, each producing the opposite side's trade direction from what
    the level originally represented. Retest/hold v1 uses real candle
    geometry, evaluated at the actual retest candle (not necessarily the
    current one): the retest candle's wick overlaps the old level AND its
    CLOSE holds on the new, flipped-favorable side -- both already proven
    by structure_utils.detect_snr_breakout_retest()'s tolerance-gated touch
    + strict-hold check, never re-derived here."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if not snapshot.snr_flip_confirmed:
            return None

        direction = _DIRECTION_MAP.get(snapshot.snr_flip_direction)
        if direction is None:
            return None

        level = snapshot.snr_flip_level
        original_role = snapshot.snr_flip_original_role
        new_role = snapshot.snr_flip_new_role
        breakout_index = snapshot.snr_flip_breakout_index
        breakout_timestamp = snapshot.snr_flip_breakout_timestamp
        retest_index = snapshot.snr_flip_retest_index
        retest_timestamp = snapshot.snr_flip_retest_timestamp
        if level is None or retest_index is None or retest_timestamp is None:
            return None

        label = f"{original_role} → {new_role} Retest"

        confidence = round(
            min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction), 1.0),
            2,
        )

        evidence_ref = {
            "source": "support_resistance_breakout_retest",
            "original_role": original_role,
            "new_role": new_role,
            "breakout_index": breakout_index,
            "breakout_timestamp": breakout_timestamp,
            "retest_index": retest_index,
            "retest_timestamp": retest_timestamp,
        }

        level_marking = make_chart_marking(
            "level",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            price=level,
            timestamp=retest_timestamp,
            candle_index=retest_index,
            evidence_ref=evidence_ref,
        )
        candle_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            timestamp=retest_timestamp,
            candle_index=retest_index,
            evidence_ref=evidence_ref,
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "SUPPORT_RESISTANCE_BREAKOUT_RETEST",
            "timestamp": snapshot.timestamp,
            "price": level,
            "chart_markings": [level_marking, candle_marking],
        }
