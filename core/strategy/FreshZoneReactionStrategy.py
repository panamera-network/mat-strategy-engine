from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import (
    Strategy, StrategySnapshot, strategy_momentum_confidence,
)

# Fix #7M — Fresh Zone Reaction v1 baseline confidence formula, reported
# explicitly per this fix's own requirement (no new zone-strength formula,
# no bias score):
#
#   confidence = BASE_CONFIDENCE
#   if active_zone_structural_evidence == "confirmed_current_event":
#       confidence += STRUCTURAL_CONFIRMATION_BONUS
#   confidence += MOMENTUM_WEIGHT * strategy_momentum_confidence(atr_normalized_momentum, direction)
#   confidence = round(min(confidence, 1.0), 2)
#
# BASE_CONFIDENCE (0.5) reflects the canonical fresh-zone eligibility
# itself (active_zone_freshness == "fresh", the strictest of the 4
# existing derive_freshness_state() labels -- never touched/mitigated/
# invalidated). STRUCTURAL_CONFIRMATION_BONUS (0.2) is a single flat,
# binary bonus -- not a scored formula -- applied only when the existing
# canonical derive_structural_evidence() (Fix #5H2) already says this
# exact zone is the current confirmed structural-event origin link
# ("confirmed_current_event"); the weaker "supported" label intentionally
# gets no bonus in this v1 baseline (deferred to a later rule audit, not
# ignored by omission). MOMENTUM_WEIGHT (0.3) scales the canonical,
# direction-agreement-gated strategy_momentum_confidence() (Fix #6AU) --
# support evidence only, never gates eligibility. Range: exactly
# [0.5, 1.0] whenever eligible (0.5 base + up to 0.2 structural + up to
# 0.3 momentum, capped at 1.0).
#
# This is a v1 baseline only -- final zone quality/touch rules and any
# richer confidence formula are explicitly deferred to a later strategy
# rule audit.
BASE_CONFIDENCE = 0.5
STRUCTURAL_CONFIRMATION_BONUS = 0.2
MOMENTUM_WEIGHT = 0.3


class FreshZoneReactionStrategy(Strategy):
    """Fix #7M — Fresh Zone Reaction v1: reacts to the canonical active
    zone (demand_engine.get_active_zone(), the same nearest-zone selection
    rule as select_active_zone()) only when it is genuinely fresh
    (derive_freshness_state() == "fresh" -- never touched, mitigated, or
    invalidated). Demand -> long, Supply -> short. No candle-pattern
    requirement, no bias requirement, no BOS/CHoCH hard gate -- eligibility
    is zone-freshness-only. Structural confirmation and momentum may only
    scale confidence once already eligible."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        zone_type = snapshot.active_zone_type
        if zone_type not in ("demand", "supply"):
            return None
        if snapshot.active_zone_freshness != "fresh":
            return None
        if snapshot.active_zone_top is None or snapshot.active_zone_bottom is None:
            # Defensive: a genuine active zone always carries real top/
            # bottom geometry -- without it there is nothing real to mark.
            return None

        if zone_type == "demand":
            direction = "long"
            label = "Fresh Demand Zone"
            price = snapshot.active_zone_top
        else:
            direction = "short"
            label = "Fresh Supply Zone"
            price = snapshot.active_zone_bottom

        confidence = BASE_CONFIDENCE
        if snapshot.active_zone_structural_evidence == "confirmed_current_event":
            confidence += STRUCTURAL_CONFIRMATION_BONUS
        confidence += MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction)
        confidence = round(min(confidence, 1.0), 2)

        marking = make_chart_marking(
            "zone",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            top=snapshot.active_zone_top,
            bottom=snapshot.active_zone_bottom,
            timestamp=snapshot.active_zone_timestamp,
            candle_index=snapshot.active_zone_index,
            evidence_ref={
                "source": "supply_demand_zones",
                "timeframe": snapshot.timeframe,
                "freshness": snapshot.active_zone_freshness,
            },
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "FRESH_ZONE",
            "timestamp": snapshot.timestamp,
            "price": price,
            "chart_markings": [marking],
        }
