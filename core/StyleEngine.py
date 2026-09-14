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

    # Step 1 (Fix #6AK) — detect zone interaction evidence BEFORE building
    # the snapshot, resolving the ordering bug Fix #6AI found: previously
    # StyleSnapshot was constructed (running compute_conviction() via
    # __post_init__) with shift_confirmed still at its dataclass default
    # (False), then detect_zone_interaction() ran only afterward — meaning
    # conviction's shift term was permanently computed against stale,
    # always-False data. Uses the public two-phase API (Fix #6AJ/#6AK):
    # detect_zone_interaction_evidence() is pure detection, no conviction
    # dependency, same single count=1 cached candle fetch as before.
    zone_evidence = shift_engine.detect_zone_interaction_evidence(structure, tf, cache=cache)

    # Step 2 — build the snapshot with all real evidence already known, so
    # __post_init__ -> compute_conviction() runs exactly once, correctly.
    snapshot = StyleSnapshot(
        symbol=symbol,
        timeframe=tf,
        mode=mode,
        direction=bias.bias_label,
        momentum=momentum.score,
        bias=bias.bias_score,
        demand=zone_label,
        structure_label=structure.structure_type,
        # Fix #6AK — needed for conviction's structure-agreement check
        # (swing mode): does the BOS/CHoCH direction agree with this
        # snapshot's own labeled direction? Not read anywhere before this
        # fix. getattr() defensively handles minimal fake/test structure
        # objects that predate this field.
        structure_direction=getattr(structure, "structure_direction", None),
        # Fix #6Z — canonical momentum evidence, reused from the already-
        # fetched `structure` snapshot (StructureEngine already computed
        # this via MomentumEngine.compute() — no extra fetch, no second
        # MomentumEngine call). `momentum` above (legacy raw score) is
        # untouched. getattr() defensively handles minimal fake/test
        # structure objects that predate this field (e.g. this file's own
        # test doubles) — None, same as the canonical "unavailable" value.
        atr_normalized_momentum=getattr(structure, "atr_normalized_momentum", None),
        # Fix #6AK — real, final zone-interaction evidence, known BEFORE
        # construction (not the dataclass defaults, not mutated
        # afterward). This is what fixes the dead shift_score bug.
        zone_interaction=zone_evidence["interacted"],
        zone_interaction_direction=zone_evidence["interaction_direction"],
        shift_confirmed=zone_evidence["shifted"],
        shift_direction=zone_evidence["shift_direction"],
    )

    # Step 3 — colorize using the now-correct snapshot.conviction. No
    # second detection/fetch: build_zone_interaction_result() is pure
    # color derivation over the already-known evidence (Fix #6AJ).
    zone_interaction_result = shift_engine.build_zone_interaction_result(zone_evidence, conviction=snapshot.conviction)

    # Step 4: Duration
    last_change_time = shift_engine.get_last_shift_change_time(symbol, tf)
    if last_change_time:
        elapsed_minutes = int((datetime.now(timezone.utc) - last_change_time).total_seconds() / 60)
        snapshot.duration = f"{elapsed_minutes} min"

    # Step 5 — assign the color fields only; zone_interaction/direction/
    # shift_confirmed/shift_direction were already set correctly at
    # construction (Step 2) and are not reassigned here.
    snapshot.zone_interaction_color = zone_interaction_result["zone_interaction_color"]
    snapshot.shift_color = zone_interaction_result["shift_color"]

    return snapshot


def build_multi_symbol_snapshot(
    bias_engine,
    candle_engine,
    momentum_engine,
    demand_engine,
    structure_engine,
    shift_engine,
    cache=None
) -> Dict[str, Any]:
    # Fix #6BQ — optional request-scoped CandleCache, threaded through to
    # get_bias_map() and every get_style_snapshot() call below so the full
    # 36x9 sweep reuses one batch fetch per (symbol, tf) instead of each
    # engine call hitting MT5 independently. None (any caller that doesn't
    # pass one) behaves exactly as before -- every downstream call already
    # accepts cache=None as its default.
    result = {}

    for symbol in SYMBOLS:
        try:
            bias_map = bias_engine.get_bias_map(symbol, TIMEFRAMES, cache=cache)

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
                    structure_engine=structure_engine,
                    cache=cache
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
