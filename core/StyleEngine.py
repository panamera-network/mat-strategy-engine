from datetime import datetime, timezone
from typing import Dict, Any
from core.core_models import StrengthDiagnostic, StyleSnapshot
from dataclasses import asdict
from mt5.constants import SYMBOLS, TIMEFRAMES  # Assuming you have this


from datetime import datetime, timezone

def get_style_snapshot(symbol, tf, mode,
                       bias_engine, momentum_engine,
                       demand_engine, structure_engine, shift_engine,
                       candle_engine=None, cache=None) -> StyleSnapshot:
    structure = structure_engine.get_snapshot(symbol, tf, cache=cache)
    bias = bias_engine.get_bias(symbol, tf, cache=cache)
    momentum = momentum_engine.get_momentum(symbol, tf, cache=cache)
    zone_label = demand_engine.get_label(symbol, tf, cache=cache)

    # Step 1: Build snapshot without shift info so conviction is computed
    snapshot = StyleSnapshot(
        symbol=symbol,
        timeframe=tf,
        mode=mode,
        direction=bias.bias_label,
        momentum=momentum.score,
        bias=bias.bias_score,
        demand=zone_label,
        structure_label=structure.structure_type
    )

    # Step 2: Detect shift with conviction-aware coloring
    shift_result = shift_engine.detect_shift(structure, tf, conviction=snapshot.conviction, cache=cache)

    # Step 3: Duration
    last_change_time = shift_engine.get_last_shift_change_time(symbol, tf)
    if last_change_time:
        elapsed_minutes = int((datetime.now(timezone.utc) - last_change_time).total_seconds() / 60)
        snapshot.duration = f"{elapsed_minutes} min"

    # Step 4: Update shift fields
    snapshot.shift_confirmed = shift_result["shifted"]
    snapshot.shift_direction = shift_result["shift_direction"]
    snapshot.shift_color = shift_result["shift_color"]

    return snapshot


def build_multi_symbol_snapshot(
    bias_engine,
    candle_engine,
    momentum_engine,
    demand_engine,
    structure_engine,
    shift_engine
) -> Dict[str, Any]:
    result = {}

    for symbol in SYMBOLS:
        try:
            bias_map = bias_engine.get_bias_map(symbol, TIMEFRAMES)

            scalping_snapshots = {}
            swing_snapshots = {}

            for tf in TIMEFRAMES:
                mode = "scalping" if tf in ["M1", "M5", "M15", "M30"] else "swing"

                snapshot = get_style_snapshot(
                    symbol=symbol,
                    tf=tf,
                    mode=mode,
                    bias_engine=bias_engine,
                    shift_engine=shift_engine,
                    candle_engine=candle_engine,
                    momentum_engine=momentum_engine,
                    demand_engine=demand_engine,
                    structure_engine=structure_engine
                )

                if mode == "scalping":
                    scalping_snapshots[tf] = asdict(snapshot)
                else:
                    swing_snapshots[tf] = asdict(snapshot)

            result[symbol] = {
                "bias": {
                    tf: {
                        "label": bias_map.get(tf, {}).get("bias_label"),
                        "score": bias_map.get(tf, {}).get("bias_score"),
                        "strength": (
                            bias_map.get(tf, {}).get("strength_diagnostic").strength
                            if isinstance(bias_map.get(tf, {}).get("strength_diagnostic"), StrengthDiagnostic)
                            else None
                        )
                    } for tf in TIMEFRAMES
                },
                "scalping": scalping_snapshots,
                "swing": swing_snapshots
            }

        except Exception as e:
            result[symbol] = {"error": str(e)}
            print(f"[{symbol}] snapshot failed: {e}")

       


    return result
