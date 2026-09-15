import importlib
import inspect
import logging
import pkgutil
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from core.core_models import StructureSnapshot
from core.strategy.strategy_models import Strategy, StrategySnapshot

logger = logging.getLogger(__name__)

# Modules in this package that are infrastructure, not strategies — never
# auto-imported as plugins. Add to this list only for non-strategy support
# code; new strategies should never need an entry here.
_EXCLUDED_MODULES = {"strategy_models", "StrategyEngine"}


def _mid_price(structure: StructureSnapshot) -> float | None:
    if structure.current_high is None or structure.current_low is None:
        return None
    return (structure.current_high + structure.current_low) / 2


def _snr_context(structure: StructureSnapshot) -> dict:
    price = _mid_price(structure)
    levels = getattr(structure, "snr_levels", []) or []
    if price is None or not levels:
        return {
            "nearest_support": None,
            "nearest_resistance": None,
            "snr_context": "neutral",
            "snr_strength": 0.0,
        }

    supports = [lvl.level for lvl in levels if str(lvl.type).lower() == "support"]
    resistances = [lvl.level for lvl in levels if str(lvl.type).lower() == "resistance"]
    nearest_support = min(supports, key=lambda level: abs(price - level), default=None)
    nearest_resistance = min(resistances, key=lambda level: abs(price - level), default=None)
    nearest_level = min(levels, key=lambda lvl: abs(price - lvl.level))
    distance = abs(price - nearest_level.level)

    candle_range = abs((structure.current_high or price) - (structure.current_low or price))
    tolerance = max(candle_range * 0.5, abs(price) * 0.0005)
    snr_type = str(nearest_level.type).lower()

    if distance <= tolerance and snr_type == "support":
        context = "at_support"
    elif distance <= tolerance and snr_type == "resistance":
        context = "at_resistance"
    elif nearest_support is not None and nearest_resistance is not None:
        context = "between_snr"
    elif nearest_support is not None:
        context = "above_support"
    elif nearest_resistance is not None:
        context = "below_resistance"
    else:
        context = "neutral"

    strength = 0.0 if tolerance <= 0 else max(0.0, min(1.0, 1.0 - distance / tolerance))

    return {
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "snr_context": context,
        "snr_strength": strength,
    }


def to_strategy_snapshot(structure: StructureSnapshot) -> StrategySnapshot:
    snr = _snr_context(structure)
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
        engulfing_strength=getattr(structure, "engulfing_strength", None),
        # Fix #7J -- straight copy from _snr_context(), no new formula, no
        # new fetch; only the 4 fields genuinely read by a committed
        # Strategy (Fix #7B).
        nearest_support=snr["nearest_support"],
        nearest_resistance=snr["nearest_resistance"],
        snr_context=snr["snr_context"],
        snr_strength=snr["snr_strength"],
        # Fix #6AS — straight copy, no recomputation, no new fetch.
        atr_normalized_momentum=getattr(structure, "atr_normalized_momentum", None),
        # Fix #7H — straight copy, no recomputation, no new fetch.
        event_timestamp=getattr(structure, "event_timestamp", None),
        event_index=getattr(structure, "event_index", None),
        event_broken_level=getattr(structure, "event_broken_level", None),
        # Fix #7K — straight copy from StructureSnapshot.recent_candles
        # (dataclass -> plain dict per entry, same conversion Output.py
        # already uses for snr_levels), no recomputation, no new fetch.
        recent_candles=[asdict(c) for c in (getattr(structure, "recent_candles", None) or [])],
        # Fix #7L — straight copy, no recomputation, no new fetch.
        pre_break_trend=getattr(structure, "pre_break_trend", None),
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
