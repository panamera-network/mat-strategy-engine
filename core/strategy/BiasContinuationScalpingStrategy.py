from typing import Dict, Optional

from core.strategy.strategy_models import (
    Strategy, StrategySnapshot, price_from_snapshot, strategy_momentum_confidence,
)


ANCHOR_TFS = ["H1", "H4"]
TRIGGER_TFS = ["M5", "M15"]
STRUCTURE_TRIGGERS = {"BOS", "CHOCH", "breakout", "reversal"}
# Fix #7B — canonical replacement for the retired
# `normalize_confidence(snapshot.momentum) >= 0.45` fallback trigger (raw,
# unsigned, per-instrument-scale, direction-blind). Empirically compared
# against a 3,990-row rolling sample across FX/JPY/Metals/Crypto/Energy at
# M15 (see Fix #7B's audit): a 0.5 ATR magnitude threshold passed 59.6%-
# 70.5% of samples depending on instrument class (still fairly uniform,
# but nearly double the old formula's ~34.5% overall magnitude-only base
# rate); a 1.0 ATR threshold passed a tightly uniform 29.8%-37.9% across
# every class -- both far more uniform than the old formula's 0%-84.7%
# instrument-scale-broken spread, but 1.0 ATR was chosen because its
# overall base rate (34.1%) most closely preserves the old gate's original
# selectivity while fixing the scale defect, and it matches the same
# "strong momentum" ATR boundary already established for Alignment's vote
# threshold (Fix #6AF) and the weak/moderate/strong bands (Fix #6Z) --
# 0.5 in strategy_momentum_confidence() terms, since that helper divides
# by 2.0 ATR. Real-world pass rate is materially lower than these
# magnitude-only figures once direction-agreement gating is applied on
# top (this is a fallback path -- it must stay rarer than the primary
# structure trigger, not replace it).
MOMENTUM_FALLBACK_CONFIDENCE_MIN = 0.5


class BiasContinuationScalpingStrategy(Strategy):
    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if snapshot.timeframe not in TRIGGER_TFS:
            return None
        if snapshot.suppression:
            return None

        symbol = snapshot.symbol
        direction = self._aligned_bias(symbol, context)
        if not direction:
            return None

        trade_side = "long" if direction == "Bullish" else "short"
        if not self._trigger_matches(snapshot, direction, trade_side):
            return None

        confluence_label, price = self._confluence(snapshot, trade_side)
        if not confluence_label:
            return None

        confidence = self._confidence(snapshot, direction)
        return {
            "symbol": symbol,
            "timeframe": snapshot.timeframe,
            "direction": trade_side,
            "reason": f"Scalping bias continuation with {confluence_label}",
            "confidence": confidence,
            "trigger": snapshot.structure_type or "bias_continuation",
            "timestamp": snapshot.timestamp,
            "price": price,
            "style": "scalping",
        }

    def _aligned_bias(self, symbol: str, context: Dict[str, StrategySnapshot]) -> Optional[str]:
        anchors = [context.get(f"{symbol}_{tf}") for tf in ANCHOR_TFS]
        if any(snap is None or snap.suppression for snap in anchors):
            return None

        biases = {snap.bias for snap in anchors if snap}
        if len(biases) == 1:
            direction = biases.pop()
            if direction in {"Bullish", "Bearish"}:
                return direction
        return None

    def _trigger_matches(self, snapshot: StrategySnapshot, direction: str, trade_side: str) -> bool:
        if snapshot.bias != direction:
            return False
        if snapshot.structure_valid and snapshot.structure_type in STRUCTURE_TRIGGERS:
            if snapshot.structure_direction in {direction, "neutral", ""}:
                return True
        # Fix #7B — canonical, direction-agreement-gated fallback (see
        # MOMENTUM_FALLBACK_CONFIDENCE_MIN above). The structure trigger
        # above remains the primary path and is checked first; this
        # fallback only fires when no confirmed structural event exists.
        return self._has_confluence(snapshot, trade_side) and strategy_momentum_confidence(
            snapshot.atr_normalized_momentum, direction
        ) >= MOMENTUM_FALLBACK_CONFIDENCE_MIN

    def _has_confluence(self, snapshot: StrategySnapshot, trade_side: str) -> bool:
        if trade_side == "long":
            return snapshot.context_zone == "demand" or snapshot.snr_context == "at_support"
        return snapshot.context_zone == "supply" or snapshot.snr_context == "at_resistance"

    def _confluence(self, snapshot: StrategySnapshot, trade_side: str) -> tuple[Optional[str], Optional[float]]:
        if trade_side == "long":
            if snapshot.context_zone == "demand":
                return "demand zone", price_from_snapshot(snapshot)
            if snapshot.snr_context == "at_support":
                return "support", snapshot.nearest_support or price_from_snapshot(snapshot)
        else:
            if snapshot.context_zone == "supply":
                return "supply zone", price_from_snapshot(snapshot)
            if snapshot.snr_context == "at_resistance":
                return "resistance", snapshot.nearest_resistance or price_from_snapshot(snapshot)
        return None, None

    def _confidence(self, snapshot: StrategySnapshot, direction: str) -> float:
        # Fix #6AV — momentum ingredient migrated to the canonical, signed,
        # direction-agreement-gated helper (Fix #6AU); `direction` here is
        # the same already-resolved "Bullish"/"Bearish" value react() used
        # for eligibility above, not a second/independent direction. Every
        # other term (base offset, SNR bonus, structure_valid bonus, cap)
        # is unchanged.
        confidence = strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction) + 0.12
        confidence += min(snapshot.snr_strength * 0.12, 0.12)
        if snapshot.structure_valid:
            confidence += 0.08
        return round(min(confidence, 1.0), 2)
