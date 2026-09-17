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
        # Fix #7M — straight copy, no recomputation, no new fetch.
        active_zone_type=getattr(structure, "active_zone_type", None),
        active_zone_top=getattr(structure, "active_zone_top", None),
        active_zone_bottom=getattr(structure, "active_zone_bottom", None),
        active_zone_freshness=getattr(structure, "active_zone_freshness", None),
        active_zone_structural_evidence=getattr(structure, "active_zone_structural_evidence", None),
        active_zone_timestamp=getattr(structure, "active_zone_timestamp", None),
        active_zone_index=getattr(structure, "active_zone_index", None),
        # Fix #7N — straight copy, no recomputation, no new fetch.
        active_zone_touch_count=getattr(structure, "active_zone_touch_count", None),
        # Fix #7N — SEPARATE mitigated-zone evidence bundle, straight copy.
        mitigated_zone_type=getattr(structure, "mitigated_zone_type", None),
        mitigated_zone_top=getattr(structure, "mitigated_zone_top", None),
        mitigated_zone_bottom=getattr(structure, "mitigated_zone_bottom", None),
        mitigated_zone_structural_evidence=getattr(structure, "mitigated_zone_structural_evidence", None),
        mitigated_zone_timestamp=getattr(structure, "mitigated_zone_timestamp", None),
        mitigated_zone_index=getattr(structure, "mitigated_zone_index", None),
        mitigated_zone_touch_count=getattr(structure, "mitigated_zone_touch_count", None),
        # Fix #7P — straight copy, no recomputation, no new fetch.
        breakout_origin_index=getattr(structure, "breakout_origin_index", None),
        breakout_origin_timestamp=getattr(structure, "breakout_origin_timestamp", None),
        retest_index=getattr(structure, "retest_index", None),
        retest_timestamp=getattr(structure, "retest_timestamp", None),
        retest_confirmed=getattr(structure, "retest_confirmed", False),
        # Fix #7S -- straight copy, no recomputation, no new fetch.
        conviction=getattr(structure, "conviction", None),
        conviction_direction=getattr(structure, "conviction_direction", None),
        # Fix #7T -- straight copy, no recomputation, no new fetch.
        choch_confirmed=getattr(structure, "choch_confirmed", False),
        choch_index=getattr(structure, "choch_index", None),
        choch_timestamp=getattr(structure, "choch_timestamp", None),
        choch_broken_level=getattr(structure, "choch_broken_level", None),
        # Fix #7T (BOS origin identity audit) -- straight copy, no
        # recomputation, no new fetch.
        bos_origin_index=getattr(structure, "bos_origin_index", None),
        bos_origin_timestamp=getattr(structure, "bos_origin_timestamp", None),
        # Fix #7U -- straight copy, no recomputation, no new fetch.
        momentum_sequence_confirmed=getattr(structure, "momentum_sequence_confirmed", False),
        momentum_sequence_direction=getattr(structure, "momentum_sequence_direction", None),
        momentum_expansion_index=getattr(structure, "momentum_expansion_index", None),
        momentum_expansion_timestamp=getattr(structure, "momentum_expansion_timestamp", None),
        momentum_expansion_value=getattr(structure, "momentum_expansion_value", None),
        momentum_pullback_index=getattr(structure, "momentum_pullback_index", None),
        momentum_pullback_timestamp=getattr(structure, "momentum_pullback_timestamp", None),
        momentum_pullback_value=getattr(structure, "momentum_pullback_value", None),
        momentum_recovery_index=getattr(structure, "momentum_recovery_index", None),
        momentum_recovery_timestamp=getattr(structure, "momentum_recovery_timestamp", None),
        momentum_recovery_value=getattr(structure, "momentum_recovery_value", None),
        # Fix #7V -- straight copy, no recomputation, no new fetch.
        current_close=getattr(structure, "current_close", None),
        # Fix #7W — straight copy, no recomputation, no new fetch.
        snr_flip_confirmed=getattr(structure, "snr_flip_confirmed", False),
        snr_flip_direction=getattr(structure, "snr_flip_direction", None),
        snr_flip_original_role=getattr(structure, "snr_flip_original_role", None),
        snr_flip_new_role=getattr(structure, "snr_flip_new_role", None),
        snr_flip_level=getattr(structure, "snr_flip_level", None),
        snr_flip_breakout_index=getattr(structure, "snr_flip_breakout_index", None),
        snr_flip_breakout_timestamp=getattr(structure, "snr_flip_breakout_timestamp", None),
        snr_flip_retest_index=getattr(structure, "snr_flip_retest_index", None),
        snr_flip_retest_timestamp=getattr(structure, "snr_flip_retest_timestamp", None),
        # Fix #7X — straight copy, no recomputation, no new fetch.
        volume_profile_source_type=getattr(structure, "volume_profile_source_type", None),
        volume_profile_range_start_timestamp=getattr(structure, "volume_profile_range_start_timestamp", None),
        volume_profile_range_end_timestamp=getattr(structure, "volume_profile_range_end_timestamp", None),
        volume_profile_poc=getattr(structure, "volume_profile_poc", None),
        volume_profile_vah=getattr(structure, "volume_profile_vah", None),
        volume_profile_val=getattr(structure, "volume_profile_val", None),
        volume_profile_total_volume=getattr(structure, "volume_profile_total_volume", None),
        volume_profile_value_area_pct=getattr(structure, "volume_profile_value_area_pct", None),
        volume_profile_num_bins=getattr(structure, "volume_profile_num_bins", None),
        # Fix #7Y — straight copy, no recomputation, no new fetch.
        balance_range_confirmed=getattr(structure, "balance_range_confirmed", False),
        balance_range_start_index=getattr(structure, "balance_range_start_index", None),
        balance_range_start_timestamp=getattr(structure, "balance_range_start_timestamp", None),
        balance_range_end_index=getattr(structure, "balance_range_end_index", None),
        balance_range_end_timestamp=getattr(structure, "balance_range_end_timestamp", None),
        balance_range_high=getattr(structure, "balance_range_high", None),
        balance_range_low=getattr(structure, "balance_range_low", None),
        balance_range_poc=getattr(structure, "balance_range_poc", None),
        balance_range_vah=getattr(structure, "balance_range_vah", None),
        balance_range_val=getattr(structure, "balance_range_val", None),
        balance_range_total_volume=getattr(structure, "balance_range_total_volume", None),
        balance_range_value_area_pct=getattr(structure, "balance_range_value_area_pct", None),
        balance_range_num_bins=getattr(structure, "balance_range_num_bins", None),
        balance_range_source_type=getattr(structure, "balance_range_source_type", None),
        # Fix #7AA — straight copy, no recomputation, no new fetch.
        inside_bar_confirmed=getattr(structure, "inside_bar_confirmed", False),
        inside_bar_direction=getattr(structure, "inside_bar_direction", None),
        inside_bar_mother_index=getattr(structure, "inside_bar_mother_index", None),
        inside_bar_mother_timestamp=getattr(structure, "inside_bar_mother_timestamp", None),
        inside_bar_mother_open=getattr(structure, "inside_bar_mother_open", None),
        inside_bar_mother_high=getattr(structure, "inside_bar_mother_high", None),
        inside_bar_mother_low=getattr(structure, "inside_bar_mother_low", None),
        inside_bar_mother_close=getattr(structure, "inside_bar_mother_close", None),
        inside_bar_children_count=getattr(structure, "inside_bar_children_count", None),
        inside_bar_children_start_index=getattr(structure, "inside_bar_children_start_index", None),
        inside_bar_children_start_timestamp=getattr(structure, "inside_bar_children_start_timestamp", None),
        inside_bar_children_end_index=getattr(structure, "inside_bar_children_end_index", None),
        inside_bar_children_end_timestamp=getattr(structure, "inside_bar_children_end_timestamp", None),
        inside_bar_breakout_index=getattr(structure, "inside_bar_breakout_index", None),
        inside_bar_breakout_timestamp=getattr(structure, "inside_bar_breakout_timestamp", None),
        inside_bar_breakout_close=getattr(structure, "inside_bar_breakout_close", None),
        # Fix #7AB — straight copy, no recomputation, no new fetch.
        three_inside_confirmed=getattr(structure, "three_inside_confirmed", False),
        three_inside_direction=getattr(structure, "three_inside_direction", None),
        three_inside_c1_index=getattr(structure, "three_inside_c1_index", None),
        three_inside_c1_timestamp=getattr(structure, "three_inside_c1_timestamp", None),
        three_inside_c1_open=getattr(structure, "three_inside_c1_open", None),
        three_inside_c1_high=getattr(structure, "three_inside_c1_high", None),
        three_inside_c1_low=getattr(structure, "three_inside_c1_low", None),
        three_inside_c1_close=getattr(structure, "three_inside_c1_close", None),
        three_inside_c2_index=getattr(structure, "three_inside_c2_index", None),
        three_inside_c2_timestamp=getattr(structure, "three_inside_c2_timestamp", None),
        three_inside_c2_open=getattr(structure, "three_inside_c2_open", None),
        three_inside_c2_high=getattr(structure, "three_inside_c2_high", None),
        three_inside_c2_low=getattr(structure, "three_inside_c2_low", None),
        three_inside_c2_close=getattr(structure, "three_inside_c2_close", None),
        three_inside_c3_index=getattr(structure, "three_inside_c3_index", None),
        three_inside_c3_timestamp=getattr(structure, "three_inside_c3_timestamp", None),
        three_inside_c3_open=getattr(structure, "three_inside_c3_open", None),
        three_inside_c3_high=getattr(structure, "three_inside_c3_high", None),
        three_inside_c3_low=getattr(structure, "three_inside_c3_low", None),
        three_inside_c3_close=getattr(structure, "three_inside_c3_close", None),
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
