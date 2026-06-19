
from asyncio.log import logger
from typing import Dict, List
from core.core_models import StructureSnapshot
from core.strategy.DoubleEngulfingStrategy import DoubleEngulfingStrategy
from core.strategy.GroupedLastCandleBiasStrategy import GroupedLastCandleBiasStrategy
from core.strategy.LastCandleBiasStrategy import LastCandleBiasStrategy
from core.strategy.ScalpingBiasCascade import ScalpingBiasCascade
from core.strategy.ZoneContinuationStrategy import ZoneContinuationStrategy
from core.strategy.strategy_models import StrategySnapshot


def to_strategy_snapshot(structure: StructureSnapshot) -> StrategySnapshot:
    return StrategySnapshot(
        symbol=structure.symbol,
        timeframe=structure.timeframe,
        bias=structure.bias,
        momentum=structure.momentum,
        strength=structure.strength,
        suppression=structure.suppression,
        suppression_reason=structure.suppression_reason,
        structure_type=structure.structure_type,
        structure_direction=structure.structure_direction,
        structure_valid=structure.structure_valid,
        context_zone=structure.context_zone,
        context_level=structure.context_level,
        timestamp=structure.timestamp,
        is_last_bias_candle=getattr(structure, "is_last_bias_candle", False),
        engulfing_sequence=getattr(structure, "engulfing_sequence", None),
        engulfing_strength=getattr(structure, "engulfing_strength", None)
    )

class StrategyEngine:
    def __init__(self):
        self.strategies = {
            "scalp": ScalpingBiasCascade(),
            "zone": ZoneContinuationStrategy(),
            "engulf": DoubleEngulfingStrategy(),
            "last_candle": LastCandleBiasStrategy(),
            "grouped_bias": GroupedLastCandleBiasStrategy()
        }

    def evaluate(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> List[Dict]:
        signals = []
        for strategy in self.strategies.values():
            signal = strategy.react(snapshot, context)
            if signal:
                signals.append(signal)

        for signal in signals:
            logger.info(f"{signal['symbol']} | {signal['timeframe']} | {signal['direction']} | {signal['reason']} | {signal['confidence']}")

        return signals
