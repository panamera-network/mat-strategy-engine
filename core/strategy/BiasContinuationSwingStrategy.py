from typing import Dict, Optional

from core.strategy.strategy_models import Strategy, StrategySnapshot, price_from_snapshot, strategy_momentum_confidence


ANCHOR_TFS = ["D1", "H4"]
TRIGGER_TFS = ["M30", "H1"]
STRUCTURE_TRIGGERS = {"BOS", "CHOCH", "breakout", "reversal"}


class BiasContinuationSwingStrategy(Strategy):
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
            "reason": f"Swing bias continuation with {confluence_label}",
            "confidence": confidence,
            "trigger": snapshot.structure_type or "bias_continuation",
            "timestamp": snapshot.timestamp,
            "price": price,
            "style": "swing",
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
        if not snapshot.structure_valid or snapshot.structure_type not in STRUCTURE_TRIGGERS:
            return False
        if snapshot.structure_direction not in {direction, "neutral", ""}:
            return False
        return self._has_confluence(snapshot, trade_side)

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
        # other term (base offset, SNR bonus, BOS bonus, cap) is unchanged.
        confidence = strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction) + 0.18
        confidence += min(snapshot.snr_strength * 0.15, 0.15)
        if snapshot.structure_type == "BOS":
            confidence += 0.05
        return round(min(confidence, 1.0), 2)
