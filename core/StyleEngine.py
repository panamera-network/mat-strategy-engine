from datetime import datetime, timezone
from typing import Dict, Any
from core.core_models import StrengthDiagnostic, StyleSnapshot
from dataclasses import asdict
from mt5.constants import SYMBOLS, TIMEFRAMES  # Assuming you have this


from datetime import datetime, timezone

def get_style_snapshot(symbol, tf, mode,
                       bias_engine, momentum_engine,
                       demand_engine, structure_engine, shift_engine,
                       candle_engine=None, cache=None, structure_snapshot=None) -> StyleSnapshot:
    # Fix #4D2 — reuse a caller-supplied StructureSnapshot (e.g. Output.py's
    # structure_map[tf], already fetched once) instead of calling
    # StructureEngine.get_snapshot() a second time. Optional and defaults to
    # None so callers that don't pass one (e.g. build_multi_symbol_snapshot())
    # keep fetching it here, unchanged.
    structure = structure_snapshot if structure_snapshot is not None else structure_engine.get_snapshot(symbol, tf, cache=cache)
    # Reuse the structure snapshot just fetched above so bias's BOS/CHoCH
    # always matches StructureEngine's — see BiasEngine.evaluate_bias().
    bias = bias_engine.get_bias(symbol, tf, structure_snapshot=structure, cache=cache)
    momentum = momentum_engine.get_momentum(symbol, tf, cache=cache)
    # Fix #4D1 — structure.context_zone already IS the canonical
    # DemandEngine.get_context() result (Fix #4C); calling get_label() here
    # would just recompute detect_zones() a second time for the same answer.
    zone_label = structure.context_zone

    # Step 1: Build snapshot without shift info so conviction is computed
    snapshot = StyleSnapshot(
        symbol=symbol,
        timeframe=tf,
        mode=mode,
        direction=bias.bias_label,
        momentum=momentum.score,
        bias=bias.bias_score,
        demand=zone_label,
        structure_label=structure.structure_type,
        # Fix #6Z — canonical momentum evidence, reused from the already-
        # fetched `structure` snapshot (StructureEngine already computed
        # this via MomentumEngine.compute() — no extra fetch, no second
        # MomentumEngine call). `momentum` above (legacy raw score) is
        # untouched. getattr() defensively handles minimal fake/test
        # structure objects that predate this field (e.g. this file's own
        # test doubles) — None, same as the canonical "unavailable" value.
        atr_normalized_momentum=getattr(structure, "atr_normalized_momentum", None),
    )

    # Step 2: Detect zone interaction with conviction-aware coloring
    # (Fix #6D — canonical name; detect_shift() still exists as an alias).
    zone_interaction_result = shift_engine.detect_zone_interaction(structure, tf, conviction=snapshot.conviction, cache=cache)

    # Step 3: Duration
    last_change_time = shift_engine.get_last_shift_change_time(symbol, tf)
    if last_change_time:
        elapsed_minutes = int((datetime.now(timezone.utc) - last_change_time).total_seconds() / 60)
        snapshot.duration = f"{elapsed_minutes} min"

    # Step 4: Update zone interaction fields — canonical (Fix #6D) plus the
    # legacy shift_* aliases, set to the exact same values so existing
    # diagnostic/alignment consumers are unaffected by this rename.
    snapshot.zone_interaction = zone_interaction_result["zone_interaction"]
    snapshot.zone_interaction_direction = zone_interaction_result["zone_interaction_direction"]
    snapshot.zone_interaction_color = zone_interaction_result["zone_interaction_color"]
    snapshot.shift_confirmed = zone_interaction_result["shifted"]
    snapshot.shift_direction = zone_interaction_result["shift_direction"]
    snapshot.shift_color = zone_interaction_result["shift_color"]

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
