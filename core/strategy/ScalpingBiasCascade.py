import logging
from typing import Dict, Optional
from core.strategy.strategy_models import Strategy, StrategySnapshot, price_from_snapshot

logger = logging.getLogger(__name__)

SCALPING_TFS = ["M1", "M5", "M15", "M30"]
ALIGNMENT_TFS = ["M15", "M30", "H1"]  # exclude M5 from context

_OPPOSITE = {"Bullish": "Bearish", "Bearish": "Bullish"}


class ScalpingBiasCascade(Strategy):
    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if snapshot.timeframe not in SCALPING_TFS:
            return None

        symbol = snapshot.symbol
        m1 = context.get(f"{symbol}_M1")

        for bias_direction, trade_direction in (("Bullish", "short"), ("Bearish", "long")):
            aligned = snapshot.bias == bias_direction and all(
                context.get(f"{symbol}_{tf}") and context[f"{symbol}_{tf}"].bias == bias_direction
                for tf in ALIGNMENT_TFS
            )
            flip_bias = _OPPOSITE[bias_direction]

            if (
                aligned and m1 and m1.bias == flip_bias and not m1.suppression
                and snapshot.structure_type == "CHOCH"
            ):
                return {
                    "symbol": symbol,
                    "timeframe": snapshot.timeframe,
                    "direction": trade_direction,
                    "reason": "Scalping bias cascade",
                    "confidence": snapshot.momentum,
                    "trigger": snapshot.structure_type,
                    "timestamp": snapshot.timestamp,
                    "price": price_from_snapshot(snapshot)
                }

            if aligned:
                logger.debug(
                    "[Cascade] %s alignment held but flip not confirmed — M1 bias: %s, suppression: %s, structure: %s",
                    bias_direction, m1.bias if m1 else "None",
                    m1.suppression if m1 else "None", snapshot.structure_type,
                )

        return None
