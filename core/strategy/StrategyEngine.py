import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Dict, List

from core.core_models import StructureSnapshot
from core.strategy.strategy_models import Strategy, StrategySnapshot

logger = logging.getLogger(__name__)

# Modules in this package that are infrastructure, not strategies — never
# auto-imported as plugins. Add to this list only for non-strategy support
# code; new strategies should never need an entry here.
_EXCLUDED_MODULES = {"strategy_models", "StrategyEngine"}


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
        current_high=structure.current_high,
        current_low=structure.current_low,
        is_last_bias_candle=getattr(structure, "is_last_bias_candle", False),
        engulfing_sequence=getattr(structure, "engulfing_sequence", None),
        engulfing_strength=getattr(structure, "engulfing_strength", None)
    )


def _discover_strategies() -> List[Strategy]:
    """Auto-load every Strategy subclass defined in core/strategy/.

    Adding a new strategy means dropping a .py file in this folder that
    defines a class inheriting from Strategy — no edits needed here.
    """
    strategies: List[Strategy] = []
    package_dir = Path(__file__).parent

    for module_info in pkgutil.iter_modules([str(package_dir)]):
        module_name = module_info.name
        if module_info.ispkg or module_name in _EXCLUDED_MODULES:
            continue

        try:
            module = importlib.import_module(f"core.strategy.{module_name}")
        except Exception:
            logger.exception("Failed to import strategy module '%s' — skipping", module_name)
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue  # imported elsewhere, not defined in this module
            if not issubclass(obj, Strategy) or obj is Strategy:
                continue
            try:
                strategies.append(obj())
            except Exception:
                logger.exception("Failed to instantiate strategy '%s' — skipping", obj.__name__)

    return strategies


class StrategyEngine:
    def __init__(self):
        self.strategies: List[Strategy] = _discover_strategies()
        self.enabled: Dict[str, bool] = {type(s).__name__: True for s in self.strategies}
        logger.info(
            "Loaded %d strategy plugin(s): %s",
            len(self.strategies),
            ", ".join(self.enabled.keys()),
        )

    def list_strategies(self) -> List[Dict]:
        """Plugin names + on/off state, for a frontend toggle list."""
        return [
            {"name": type(s).__name__, "enabled": self.enabled[type(s).__name__]}
            for s in self.strategies
        ]

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Returns False if no strategy with that name is loaded."""
        if name not in self.enabled:
            return False
        self.enabled[name] = enabled
        return True

    def evaluate(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> List[Dict]:
        signals = []
        for strategy in self.strategies:
            if not self.enabled[type(strategy).__name__]:
                continue
            try:
                signal = strategy.react(snapshot, context)
            except Exception:
                logger.exception(
                    "Strategy '%s' raised while evaluating %s [%s] — skipping",
                    type(strategy).__name__, snapshot.symbol, snapshot.timeframe,
                )
                continue
            if signal:
                signals.append(signal)

        for signal in signals:
            logger.info(f"{signal['symbol']} | {signal['timeframe']} | {signal['direction']} | {signal['reason']} | {signal['confidence']}")

        return signals


# Shared singleton — import this instead of instantiating StrategyEngine()
# directly, otherwise callers (api/core_router.py, core/Output/Output.py)
# end up with disconnected enabled/disabled state, same class of bug as the
# old split-brain SnapshotCache.
strategy_engine = StrategyEngine()
