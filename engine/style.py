from dataclasses import asdict
from typing import List

from engine.bias_map import derive_direction
from engine.core_models import StrategySnapshot
from engine.demand import fetch_demand_label

from engine.engine_core import compute_signal_duration, detect_shift, get_bias_map
from engine.momentum_engine import fetch_momentum_score
from engine.price import fetch_latest_price_snapshot


def get_scalping_snapshot(symbol: str, bias_map: dict) -> StrategySnapshot:
    tf = "M5"
    direction = derive_direction(bias_map)
    shift = detect_shift(symbol, mode="scalping", price=fetch_latest_price_snapshot(symbol, tf))
    momentum = fetch_momentum_score(symbol, tf)
    demand = fetch_demand_label(symbol, tf)
    duration = f"{compute_signal_duration(symbol, tf)} min"

    snapshot = StrategySnapshot(
        direction=direction,
        shift=shift,
        momentum=momentum,
        demand=demand,
        duration=duration
    )
    snapshot.compute_conviction()
    return snapshot

def get_swing_snapshot(symbol: str, bias_map: dict) -> StrategySnapshot:
    tf = "H1"
    direction = derive_direction(bias_map)
    shift = detect_shift(symbol, mode="swing", price=fetch_latest_price_snapshot(symbol, tf))
    momentum = fetch_momentum_score(symbol, tf)
    demand = fetch_demand_label(symbol, tf)
    duration = f"{compute_signal_duration(symbol, tf)} hr"

    snapshot = StrategySnapshot(
        direction=direction,
        shift=shift,
        momentum=momentum,
        demand=demand,
        duration=duration
    )
    snapshot.compute_conviction()
    return snapshot

def build_multi_symbol_snapshot(symbols: List[str]) -> dict:
    result = {}
    for symbol in symbols:
        try:
            bias_map = get_bias_map(symbol)
            scalping = get_scalping_snapshot(symbol, bias_map)
            swing = get_swing_snapshot(symbol, bias_map)

            result[symbol] = {
                "bias": bias_map,
                "scalping": asdict(scalping),
                "swing": asdict(swing)
            }
        except Exception as e:
            result[symbol] = {"error": str(e)}
            print(f"[{symbol}] snapshot failed: {e}")
    return result

