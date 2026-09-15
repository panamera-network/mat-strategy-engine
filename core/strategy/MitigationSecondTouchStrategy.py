from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import (
    Strategy, StrategySnapshot, strategy_momentum_confidence,
)

# Fix #7N — Touched Zone / Mitigation v1 baseline confidence formula,
# reported explicitly per this fix's own requirement (no new zone-strength
# formula, no bias score, no other quality scoring):
#
#   confidence = BASE_TOUCHED (0.5) or BASE_MITIGATION (0.4), by setup type
#   if structural_evidence == "confirmed_current_event":
#       confidence += STRUCTURAL_CONFIRMATION_BONUS (0.2)
#   confidence += MOMENTUM_WEIGHT (0.3) * strategy_momentum_confidence(atr_normalized_momentum, direction)
#   confidence = round(min(confidence, 1.0), 2)
#
# The two base values are the one place this v1 lets setup type affect
# confidence, and only for a clear canonical reason: derive_freshness_state()
# (Fix #5H2) itself already ranks "mitigated" as a WEAKER state than
# "touched" (mitigated outranks touched in its priority order precisely
# because a close has already landed back inside the zone -- a real
# violation "touched" alone does not have). BASE_MITIGATION (0.4) is
# lower than BASE_TOUCHED (0.5) to reflect that existing, canonical
# ranking -- not a new zone-strength score. STRUCTURAL_CONFIRMATION_BONUS
# and MOMENTUM_WEIGHT reuse the exact same shape/values as
# FreshZoneReactionStrategy (Fix #7M). Range: Touched Zone [0.5, 1.0],
# Mitigation [0.4, 0.9].
#
# This is a v1 baseline only -- final reaction-quality/entry rules and any
# richer confidence formula are explicitly deferred to a later rule audit.
BASE_TOUCHED = 0.5
BASE_MITIGATION = 0.4
STRUCTURAL_CONFIRMATION_BONUS = 0.2
MOMENTUM_WEIGHT = 0.3


class MitigationSecondTouchStrategy(Strategy):
    """Fix #7N — Touched Zone / Mitigation v1: reacts to a canonical zone
    that has already reacted once, sourced from TWO SEPARATE evidence
    bundles on StrategySnapshot:

    - Touched Zone setup: active_zone_* (Fix #7M's existing active-zone
      selection, unchanged) when active_zone_freshness == "touched" --
      zone still valid, at least one wick-overlap visit, never yet closed
      back inside.
    - Mitigation setup: mitigated_zone_* (Fix #7N's new, SEPARATE
      get_nearest_mitigated_zone() selector -- a sibling to
      get_active_zone(), which is never modified) -- a zone that has
      already been closed back into once, but not yet invalidated.

    These are two independent selectors over the same canonical zone
    list, so BOTH bundles may be populated on the same snapshot (e.g. a
    touched zone and a separate mitigated zone at different price
    levels). Priority (v1 behavior only, revisit at the next rule audit):
    Touched Zone is checked first; Mitigation only if Touched Zone is not
    eligible; otherwise reject. fresh/invalidated/unknown are rejected on
    both paths (an invalidated zone can never appear in either bundle --
    both selectors require valid == True).

    Demand -> long, Supply -> short. No candle-pattern requirement, no
    bias gate, no BOS/CHoCH hard gate -- eligibility is
    zone-freshness-only.

    Audit note (Fix #7N, confirmed with actual synthetic candle timelines
    run through detect_zones() -- see Fix #7N's own audit report):
    derive_freshness_state()'s "touched" label means "at least one
    wick-overlap visit, never closed back in" -- it does NOT distinguish
    a zone that reacted once before and is now being revisited a second
    time from a zone experiencing its very first visit right now (both
    produce identical touch_count/freshness evidence). "Touched Zone" is
    the deliberately conservative v1 label for that whole state -- it
    never claims a specific touch number. touch_count is exposed on both
    bundles purely as
    transparency evidence in the marking's evidence_ref, never as an
    eligibility gate, and never recomputed here.
    """

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        result = self._react_touched(snapshot)
        if result is not None:
            return result
        return self._react_mitigated(snapshot)

    def _react_touched(self, snapshot: StrategySnapshot) -> Optional[Dict]:
        zone_type = snapshot.active_zone_type
        if zone_type not in ("demand", "supply"):
            return None
        if snapshot.active_zone_freshness != "touched":
            return None
        if snapshot.active_zone_top is None or snapshot.active_zone_bottom is None:
            return None

        direction = "long" if zone_type == "demand" else "short"
        price = snapshot.active_zone_top if direction == "long" else snapshot.active_zone_bottom
        zone_noun = "Demand" if zone_type == "demand" else "Supply"

        confidence = self._confidence(BASE_TOUCHED, snapshot.active_zone_structural_evidence, snapshot, direction)

        marking = make_chart_marking(
            "zone",
            type(self).__name__,
            snapshot.timeframe,
            f"Touched {zone_noun} Zone",
            direction=direction,
            top=snapshot.active_zone_top,
            bottom=snapshot.active_zone_bottom,
            timestamp=snapshot.active_zone_timestamp,
            candle_index=snapshot.active_zone_index,
            evidence_ref={
                "source": "supply_demand_zones",
                "timeframe": snapshot.timeframe,
                "freshness": snapshot.active_zone_freshness,
                "touch_count": snapshot.active_zone_touch_count,
            },
        )

        return self._signal(snapshot, direction, "Touched Zone", confidence, price, marking)

    def _react_mitigated(self, snapshot: StrategySnapshot) -> Optional[Dict]:
        zone_type = snapshot.mitigated_zone_type
        if zone_type not in ("demand", "supply"):
            return None
        if snapshot.mitigated_zone_top is None or snapshot.mitigated_zone_bottom is None:
            return None

        direction = "long" if zone_type == "demand" else "short"
        price = snapshot.mitigated_zone_top if direction == "long" else snapshot.mitigated_zone_bottom
        zone_noun = "Demand" if zone_type == "demand" else "Supply"

        confidence = self._confidence(BASE_MITIGATION, snapshot.mitigated_zone_structural_evidence, snapshot, direction)

        marking = make_chart_marking(
            "zone",
            type(self).__name__,
            snapshot.timeframe,
            f"Mitigated {zone_noun} Zone",
            direction=direction,
            top=snapshot.mitigated_zone_top,
            bottom=snapshot.mitigated_zone_bottom,
            timestamp=snapshot.mitigated_zone_timestamp,
            candle_index=snapshot.mitigated_zone_index,
            evidence_ref={
                "source": "supply_demand_zones",
                "timeframe": snapshot.timeframe,
                "freshness": "mitigated",
                "touch_count": snapshot.mitigated_zone_touch_count,
            },
        )

        return self._signal(snapshot, direction, "Mitigation", confidence, price, marking)

    @staticmethod
    def _confidence(base: float, structural_evidence: Optional[str], snapshot: StrategySnapshot, direction: str) -> float:
        confidence = base
        if structural_evidence == "confirmed_current_event":
            confidence += STRUCTURAL_CONFIRMATION_BONUS
        confidence += MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction)
        return round(min(confidence, 1.0), 2)

    @staticmethod
    def _signal(snapshot: StrategySnapshot, direction: str, reason: str, confidence: float, price, marking) -> Dict:
        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": reason,
            "confidence": confidence,
            "trigger": "ZONE_REACTION",
            "timestamp": snapshot.timestamp,
            "price": price,
            "chart_markings": [marking],
        }
