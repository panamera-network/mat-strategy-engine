from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, price_from_snapshot

# Fix #7U — Momentum Pullback Recovery v1 baseline confidence formula,
# reported explicitly per this fix's own requirement (canonical recovery
# momentum magnitude only, no zone/bias/structure/candle-pattern
# scoring):
#
#   confidence = round(min(abs(recovery_momentum) / (RECOVERY_FLOOR * CONFIDENCE_SATURATION_MULTIPLIER), 1.0), 2)
#
# RECOVERY_FLOOR (1.0 ATR) is MomentumEngine's own RECOVERY_STRONG_
# THRESHOLD -- the eligibility floor itself, reused verbatim, not a
# second number. CONFIDENCE_SATURATION_MULTIPLIER (2.0) is the SAME
# floor-to-saturation multiplier Fix #7O's MomentumExpansionStrategy
# already established for this exact shape ("full confidence at 2x the
# eligibility floor") -- here it lands saturation at 2.0 ATR, which is
# also MomentumEngine's own EXPANSION_THRESHOLD, a coincidental but
# meaningful landmark: full confidence once the recovery is at least as
# strong as the original expansion stage itself, not an independently
# invented number. Range: exactly [0.5, 1.0] whenever eligible (0.5 at
# the recovery floor, rising to 1.0 at 2.0 ATR and beyond).
RECOVERY_FLOOR = 1.0
CONFIDENCE_SATURATION_MULTIPLIER = 2.0


class MomentumPullbackRecoveryStrategy(Strategy):
    """Fix #7U — Momentum Pullback Recovery v1: a SEQUENCE confirmation
    strategy over canonical atr_normalized_momentum history (never the
    legacy raw `.momentum` field, never inferred from a single current
    reading). Eligibility requires MomentumEngine.detect_pullback_
    recovery()'s own StrategySnapshot.momentum_sequence_confirmed to be
    True -- a genuine, earlier, same-direction momentum expansion,
    followed by a later weak pullback, followed by the CURRENT reading
    recovering strong again in that same direction (see
    MomentumEngine.detect_pullback_recovery()'s own docstring for the
    full audit rationale: threshold provenance, the explicit direction-
    flip-during-pullback decision, and the stale-sequence-identity
    protection against pairing an old expansion with an unrelated later
    recovery across an intervening opposite expansion).

    This strategy performs no momentum computation of its own -- it only
    reads the already-computed sequence fields. No zone requirement, no
    structure requirement, no candle-pattern requirement, no bias gate."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if not snapshot.momentum_sequence_confirmed:
            return None
        if snapshot.momentum_sequence_direction not in ("Bullish", "Bearish"):
            return None

        if (
            snapshot.momentum_expansion_index is None or snapshot.momentum_expansion_timestamp is None
            or snapshot.momentum_pullback_index is None or snapshot.momentum_pullback_timestamp is None
            or snapshot.momentum_recovery_index is None or snapshot.momentum_recovery_timestamp is None
            or snapshot.momentum_recovery_value is None
        ):
            # Defensive: momentum_sequence_confirmed=True should never
            # appear without this full geometry (the upstream sequence-
            # evidence wiring only ever sets them together), but never
            # fabricate a marking if it somehow does.
            return None
        if not (snapshot.momentum_expansion_index < snapshot.momentum_pullback_index < snapshot.momentum_recovery_index):
            # Defensive re-check of the ordering the upstream evidence
            # already enforces -- never trusts momentum_sequence_confirmed
            # alone without re-checking the ordering it implies (same
            # defense-in-depth pattern used for CHoCH->BOS, Fix #7T).
            return None

        direction = "long" if snapshot.momentum_sequence_direction == "Bullish" else "short"
        label = "Bullish Momentum Pullback Recovery" if direction == "long" else "Bearish Momentum Pullback Recovery"

        recovery_momentum = snapshot.momentum_recovery_value
        confidence = round(min(abs(recovery_momentum) / (RECOVERY_FLOOR * CONFIDENCE_SATURATION_MULTIPLIER), 1.0), 2)

        expansion_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "Momentum Expansion",
            direction=direction,
            timestamp=snapshot.momentum_expansion_timestamp,
            candle_index=snapshot.momentum_expansion_index,
            evidence_ref={"source": "momentum_pullback_recovery", "role": "expansion", "atr_normalized_momentum": snapshot.momentum_expansion_value},
        )
        pullback_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "Momentum Pullback",
            direction=direction,
            timestamp=snapshot.momentum_pullback_timestamp,
            candle_index=snapshot.momentum_pullback_index,
            evidence_ref={"source": "momentum_pullback_recovery", "role": "pullback", "atr_normalized_momentum": snapshot.momentum_pullback_value},
        )
        recovery_marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            "Momentum Recovery",
            direction=direction,
            timestamp=snapshot.momentum_recovery_timestamp,
            candle_index=snapshot.momentum_recovery_index,
            evidence_ref={"source": "momentum_pullback_recovery", "role": "recovery", "atr_normalized_momentum": recovery_momentum},
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "MOMENTUM_PULLBACK_RECOVERY",
            "timestamp": snapshot.timestamp,
            "price": price_from_snapshot(snapshot),
            "chart_markings": [expansion_marking, pullback_marking, recovery_marking],
        }
