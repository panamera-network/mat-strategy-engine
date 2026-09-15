import logging
from dataclasses import asdict
from datetime import datetime, timezone
from collections import OrderedDict

from core.Output.alignment_signal import compute_alignment_signal, compute_signal_health
from core.Output.build_scalping import build_scalping_diagnostic
from core.Output.diagnostic_models import cfg, BIAS_ORDER, SCALPING_ORDER, SWING_ORDER
from core.Output.health_log import build_symbol_health
from core.Output.helper import add_display_percentages, strip_nulls
from core.Output.swing_diag import enrich_swing_with_diagnostic
from core.demand_engine import classify_zones, derive_freshness_state, derive_structural_evidence
from core.SnapshotCache import snapshot_cache
from core.StyleEngine import get_style_snapshot
from core.core_models import StrengthDiagnostic
from core.strategy.StrategyEngine import strategy_engine, to_strategy_snapshot
from mt5.constants import SYMBOLS, TIMEFRAMES

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")

SCALPING_TFS = set(SCALPING_ORDER)
SWING_TFS = [tf for tf in TIMEFRAMES if tf not in SCALPING_TFS]

# Normalization thresholds — named instead of scattered magic numbers
MAX_BIAS = 4.0
ALIGNMENT_HISTORY_LIMIT = 10
# Fix #6Z — canonical momentum display bands, in ATR units (Fix #6X/#6Y's
# audit): a 3-bar displacement of less than half an ATR is "weak", up to a
# full ATR is "moderate", a full ATR or more is "strong". Replaces the old
# MOMENTUM_BAND_WEAK/MOMENTUM_BAND_MODERATE (0.2/0.5), which were tuned
# against the legacy raw, unscaled momentum score — those constants had no
# other callers and are removed rather than left dead.
ATR_MOMENTUM_MODERATE_THRESHOLD = 0.5
ATR_MOMENTUM_STRONG_THRESHOLD = 1.0
# Fix #6AB — presentation reference/cap for momentum_conf, in ATR units.
# Not a physical maximum (atr_normalized_momentum itself is unclamped, see
# MomentumEngine.py) -- just the point at which momentum_conf saturates to
# 100%. Chosen because it extends Fix #6Z's weak/moderate/strong ATR
# landmarks (0.5/1.0) by one more step, landing exactly on
# confidence_color's existing 25/50/75 tier boundaries at 0.5/1.0/1.5 ATR
# (Fix #6AA's audit, Q6). Deliberately its own named constant -- it
# governs only momentum_conf's presentation path.
MOMENTUM_CONF_ATR_REFERENCE = 2.0


def _momentum_band(momentum: float | None) -> str | None:
    """Fix #6Z — canonical band, sourced from atr_normalized_momentum
    (signed, dimensionless, no clamp — see MomentumEngine.py). abs() is
    applied internally (not by the caller) so a bullish and bearish
    reading of equal magnitude always get the same label, regardless of
    what a future caller passes in (Fix #6X's Q9 finding: relying on the
    caller to pre-abs() is a fragile, unenforced contract). None
    (canonical value unavailable) returns None explicitly — never a
    guessed "weak"."""
    if momentum is None:
        return None
    abs_momentum = abs(momentum)
    if abs_momentum < ATR_MOMENTUM_MODERATE_THRESHOLD:
        return "weak"
    if abs_momentum < ATR_MOMENTUM_STRONG_THRESHOLD:
        return "moderate"
    return "strong"


def _normalize_snapshot(snap) -> dict:
    """
    Convert a snapshot object/dict into the display-ready dict shape.
    Single source of truth for the demand->zone rename and momentum
    banding/coloring, previously duplicated for scalping and swing.
    """
    snap_dict = snap.__dict__.copy() if hasattr(snap, "__dict__") else dict(snap)

    if "demand" in snap_dict:
        snap_dict["zone"] = snap_dict.pop("demand")

    # Fix #6BM — the checks["demand_supports"]->"zone_supports" and
    # conviction_breakdown["demand"]->"zone_score" rename branches that used
    # to live here were removed: Fix #6BL's audit confirmed both were
    # unreachable dead code. _normalize_snapshot() only ever runs on a raw
    # per-tf StyleSnapshot dict (asdict(StyleSnapshot)), which has no
    # "checks" field at all (that key only exists inside the separate
    # "diagnostic" node, which never passes through this function); and
    # compute_conviction() (core_models.py) already names its zone/demand
    # term "zone_score" directly at the source for both modes, so
    # conviction_breakdown never contains a "demand" key to rename. Neither
    # branch ever fired in production — confirmed by tracing every call
    # site, not by behavior change here.

    if "momentum" in snap_dict:
        # Fix #6AD — this block used to also set snap_dict["momentum_color"]
        # here (confidence_color(abs(legacy momentum)/2.0*100)), but
        # that write was always overwritten later by
        # add_display_percentages() (core/Output/helper.py, Fix #6AC) before
        # the value ever reached a consumer — confirmed dead by live
        # comparison across all 36 symbols during Fix #6AA/#6AC's audits.
        # Removed; momentum_color is now set exactly once, downstream.
        momentum = float(f"{snap_dict['momentum']:.4f}")
        snap_dict["momentum"] = momentum

    # Fix #6Z — momentum_band migrated to canonical atr_normalized_momentum
    # (StyleSnapshot's additive field, sourced from
    # StructureSnapshot.atr_normalized_momentum — see StyleEngine.py).
    # Deliberately independent of the legacy `momentum` key above.
    if "atr_normalized_momentum" in snap_dict:
        snap_dict["momentum_band"] = _momentum_band(snap_dict["atr_normalized_momentum"])

    return snap_dict


def _normalize_snapshot_map(snapshot_map: dict) -> dict:
    return {tf: _normalize_snapshot(snap) for tf, snap in snapshot_map.items()}


def _canonical_structure_bias(bias_label: str) -> str:
    """Fix #7C — maps BiasEngine.evaluate_bias()'s own "uptrend"/
    "downtrend"/"neutral" vocabulary onto the "Bullish"/"Bearish"/
    "Neutral" vocabulary StructureSnapshot.bias/StrategySnapshot.bias and
    every Strategy plugin already expect. Not a new formula -- this is
    the exact inverse of the mapping BiasEngine.evaluate_bias() itself
    already performs internally when deriving bias_label from a confirmed
    BOS/CHoCH's structure_direction ("uptrend" if direction == "Bullish"
    else "downtrend"). Any unrecognized label maps to "Neutral", never
    guessed into a direction."""
    if bias_label == "uptrend":
        return "Bullish"
    if bias_label == "downtrend":
        return "Bearish"
    return "Neutral"


def _update_alignment_history(prev_snapshot: dict, history_key: str, alignment: dict) -> list:
    history = prev_snapshot.get(history_key, [])
    history.append(alignment["confidence_pct"])
    history = history[-ALIGNMENT_HISTORY_LIMIT:]
    alignment["confidence_history"] = history
    return history


def _build_bias_ordered(bias_map: dict) -> OrderedDict:
    bias_ordered = OrderedDict()
    for tf in BIAS_ORDER:
        tf_data = bias_map.get(tf, {})
        score_val = tf_data.get("bias_score")
        strength_diag = tf_data.get("strength_diagnostic")
        strength_val = strength_diag.strength if isinstance(strength_diag, StrengthDiagnostic) else None
        # Fix #6O — canonical body_dominance, additive alongside the
        # untouched legacy "strength" key above. Same underlying value as
        # strength_diag.avg_body_ratio (see StrengthDiagnostic.body_dominance),
        # raw [0,1] range, no new computation.
        body_dominance_val = strength_diag.body_dominance if isinstance(strength_diag, StrengthDiagnostic) else None

        bias_ordered[tf] = {
            "label": tf_data.get("bias_label"),
            "score": score_val,
            "strength": strength_val,
            "body_dominance": body_dominance_val,
        }
        # Fix #6BM — the score_color = confidence_color(pct) computation
        # that used to live here was removed: Fix #6BL's audit confirmed it
        # was always overwritten by add_display_percentages() (helper.py)
        # later in the same request, before this value ever reached a
        # consumer — the same dead pattern Fix #6AD already found and
        # removed once for momentum_color. The final score_color a caller
        # actually sees is produced exclusively by add_display_percentages().
    return bias_ordered


def _compute_signal_confidence(bias_ordered: dict, scalping_snapshots: dict, scalping_alignment: dict) -> tuple:
    bias_scores = [v["score"] for v in bias_ordered.values() if v.get("score") is not None]
    bias_conf = round(sum(abs(s) / MAX_BIAS * 100 for s in bias_scores) / len(bias_scores), 1) if bias_scores else 0

    # Fix #6AB — momentum_conf now sources canonical atr_normalized_momentum
    # instead of the legacy raw StyleSnapshot.momentum (Fix #6AA's audit
    # found the legacy numerator produced up to 932,857% under the old
    # formula, e.g. BTCUSD_i's signal_health.score_pct reading 733%).
    # MOMENTUM_CONF_ATR_REFERENCE is a presentation reference/cap, not the
    # physical maximum atr_normalized_momentum can reach (it stays
    # unclamped elsewhere, per Fix #6V) -- each per-tf pct is clamped to
    # 100 individually so one extreme reading can't drag the average past
    # 100 on its own. Deliberately a separate constant from helper.py's
    # MOMENTUM_PCT_ATR_REFERENCE (Fix #6AC) -- same numeric value today,
    # separate presentation paths (momentum_conf here vs. live
    # momentum_pct/momentum_color there).
    mom_vals = [
        min(abs(scalping_snapshots[tf]["atr_normalized_momentum"]) / MOMENTUM_CONF_ATR_REFERENCE * 100, 100.0)
        for tf in SCALPING_ORDER
        if scalping_snapshots.get(tf, {}).get("atr_normalized_momentum") is not None
    ]
    momentum_conf = round(sum(mom_vals) / len(mom_vals), 1) if mom_vals else 0

    align_conf = scalping_alignment["confidence_pct"] if scalping_alignment else 0
    return bias_conf, momentum_conf, align_conf


def _build_structure_context(symbol: str, structure_engine, cache=None, zones_map: dict = None) -> dict:
    """Fetch one raw StructureSnapshot per timeframe — single source for
    strategy evaluation, SNR levels, order blocks, and FVGs below, so we
    don't re-fetch structure data per feature.

    Fix #4D3 — optional zones_map (request-scoped, built once in
    _build_symbol_snapshot()) is forwarded per-tf so StructureEngine's
    DemandEngine.get_context() call reuses it instead of recomputing
    detect_zones(). None (any other caller) behaves exactly as before."""
    structure_map = {}
    for tf in BIAS_ORDER:
        zones = zones_map.get(tf) if zones_map else None
        structure = structure_engine.get_snapshot(symbol, tf, cache=cache, zones=zones)
        if structure:
            structure_map[tf] = structure
    return structure_map


def _build_strategy_signals(symbol: str, structure_map: dict) -> list:
    """Run every loaded strategy plugin across all timeframes for this symbol."""
    context = {
        f"{symbol}_{tf}": to_strategy_snapshot(structure)
        for tf, structure in structure_map.items()
    }

    signals = []
    for tf in structure_map:
        snap = context.get(f"{symbol}_{tf}")
        if snap:
            signals.extend(strategy_engine.evaluate(snap, context))
    return signals


def _build_structure_extras(structure_map: dict) -> tuple:
    """Per-timeframe SNR levels, order blocks, FVGs, swing points, and
    BOS/CHoCH events — all read directly off the StructureSnapshot objects
    already in structure_map (Fix #2's swing_points/event_broken_level/
    event_index/event_timestamp/structure_type/structure_direction). No
    recalculation, no new StructureEngine calls.

    structure_events' shape (type/direction/broken_level/event_index/
    event_timestamp) is the canonical engine contract (Fix #3) — StructureEngine
    is the single source of truth for this evidence; this is a straight
    projection of its fields, not a second/derived definition."""
    snr_levels = {tf: [asdict(lvl) for lvl in s.snr_levels] for tf, s in structure_map.items() if s.snr_levels}
    order_blocks = {tf: [asdict(ob) for ob in s.order_blocks] for tf, s in structure_map.items() if s.order_blocks}
    fvg = {tf: [asdict(f) for f in s.fvg] for tf, s in structure_map.items() if s.fvg}
    swing_points = {tf: [asdict(sp) for sp in s.swing_points] for tf, s in structure_map.items() if s.swing_points}
    structure_events = {
        tf: {
            "type": s.structure_type,
            "direction": s.structure_direction,
            "broken_level": s.event_broken_level,
            "event_index": s.event_index,
            "event_timestamp": s.event_timestamp,
            # Fix #5F2 — structural leg origin evidence (additive; not a
            # zone reference, not a history — a single companion reference
            # for this same event).
            "leg_origin_index": s.leg_origin_index,
            "leg_origin_timestamp": s.leg_origin_timestamp,
            "leg_origin_price": s.leg_origin_price,
            "leg_origin_swing_label": s.leg_origin_swing_label,
            # Fix #5G1 — deterministic zone <-> leg origin link, minimal
            # evidence only (never the whole zone object). Wiring only —
            # the matching rule itself lives in
            # core.demand_engine.link_zone_to_leg_origin().
            "origin_zone_type": s.origin_zone_type,
            "origin_zone_timestamp": s.origin_zone_timestamp,
            "origin_zone_top": s.origin_zone_top,
            "origin_zone_bottom": s.origin_zone_bottom,
            # Fix #6C — the two-swing trend read before this event's break
            # was evaluated (see structure_utils.detect_structure_event()).
            # Wiring only; the value itself is unchanged from what BOS/CHoCH
            # was decided against.
            "pre_break_trend": s.pre_break_trend,
        }
        for tf, s in structure_map.items()
        if s.structure_valid
    }
    return snr_levels, order_blocks, fvg, swing_points, structure_events


def _build_momentum_evidence(structure_map: dict) -> dict:
    """Fix #6V — canonical signed, dimensionless momentum evidence
    (slope2/ATR14, no clamp/multiplier — Fix #6U's audit conclusion).
    Read directly off StructureSnapshot.atr_normalized_momentum, already
    computed via MomentumEngine.compute() during structure_map's
    construction above — no new engine calls, no extra candle fetch.

    Exposed per timeframe regardless of whether a BOS/CHoCH is confirmed
    (unlike structure_events, which is filtered to structure_valid=True) —
    this is a general momentum signal, not a structural-event fact. None
    for a tf whenever MomentumEngine didn't have enough candles for a
    genuine 14-period ATR (see MomentumEngine.ATR14_MIN_CANDLES);
    StructureEngine's canonical path always supplies enough, so this is
    only ever None if called with an unusually small candle window.

    Additive only — StyleSnapshot.momentum, alignment's ±0.3 check,
    conviction, momentum bands/colors, and Suppression are untouched and
    do not read this key."""
    return {
        tf: {"atr_normalized_momentum": s.atr_normalized_momentum}
        for tf, s in structure_map.items()
    }


def _build_supply_demand_zones(symbol: str, demand_engine, cache=None, zones_map: dict = None, structure_map: dict = None) -> dict:
    """Fix #4D3 — reuses the same request-scoped zones_map StructureEngine's
    context already consumed above, instead of calling
    demand_engine.get_zones() (a second detect_zones() run) again here.
    zones_map omitted (any other caller) falls back to the original
    per-tf get_zones() call, unchanged.

    Fix #5C — classification is included in the serialized dict now:
    _build_symbol_snapshot() classifies zones_map's zones in place (via
    classify_zones(), using structure_map's swing_points) before this
    function ever runs, so every zone's classification here is a real
    verdict, not the unfired "unknown" default Fix #5B excluded this
    field for. A caller that supplies zones_map without classifying it
    first (or omits zones_map entirely) still gets a valid dict — the
    classification would just honestly read "unknown".

    Fix #5H2 — structural_evidence/freshness_state are attached per zone
    here (wiring only; the reasoning rule itself lives in
    core.demand_engine.derive_structural_evidence()/derive_freshness_state()).
    structural_evidence needs the current event's origin_zone_* (from this
    tf's StructureSnapshot, if any) to know which zone — if any — is the
    current confirmed link; structure_map omitted (or no snapshot/no
    confirmed link for a tf) behaves as "no current origin zone", so every
    zone on that tf reads at most "supported"/"unconfirmed", never a forced
    confirmation."""
    zones = {}
    for tf in BIAS_ORDER:
        tf_raw_zones = zones_map.get(tf, []) if zones_map is not None else demand_engine.get_zones(symbol, tf, cache=cache)
        structure = structure_map.get(tf) if structure_map else None
        origin_type = structure.origin_zone_type if structure else None
        origin_timestamp = structure.origin_zone_timestamp if structure else None
        origin_top = structure.origin_zone_top if structure else None
        origin_bottom = structure.origin_zone_bottom if structure else None

        tf_zones = []
        for z in tf_raw_zones:
            if not z.valid:
                continue
            zone_dict = asdict(z)
            zone_dict["structural_evidence"] = derive_structural_evidence(
                z, origin_type, origin_timestamp, origin_top, origin_bottom
            )
            zone_dict["freshness_state"] = derive_freshness_state(z)
            tf_zones.append(zone_dict)

        if tf_zones:
            zones[tf] = tf_zones
    return zones


def _build_symbol_snapshot(
    symbol: str,
    prev_snapshot: dict,
    bias_engine,
    candle_engine,
    momentum_engine,
    demand_engine,
    structure_engine,
    shift_engine,
    cache=None,
) -> dict:
    # Fix #4D3 — one raw zone list per timeframe, request-scoped to this
    # symbol's build only (not a global/persistent cache — discarded when
    # this function returns). Built once here via get_zones() (the single
    # detect_zones() call per tf) and reused below by StructureEngine's
    # DemandEngine.get_context() call and by _build_supply_demand_zones(),
    # instead of each recomputing it independently.
    zones_map = {tf: demand_engine.get_zones(symbol, tf, cache=cache) for tf in BIAS_ORDER}

    # Fetched before bias_map so BiasEngine can consume the same BOS/CHoCH
    # result instead of detecting structure independently (single source of
    # truth — see BiasEngine.evaluate_bias()). Also reused below for SNR
    # levels, order blocks, FVGs, and strategy evaluation — one fetch either way.
    structure_map = _build_structure_context(symbol, structure_engine, cache=cache, zones_map=zones_map)

    # Fix #5C — classify each tf's zones now that structure_map (with
    # swing_points) is available for the same tf. Reuses zones_map's
    # already-fetched zones and structure_map's already-computed
    # swing_points in place — no new detect_zones() or get_snapshot()
    # calls, no change to zone detection/selector. BOS/CHoCH not used
    # (per Fix #5A/#5B).
    for tf in BIAS_ORDER:
        structure = structure_map.get(tf)
        classify_zones(zones_map.get(tf, []), structure.swing_points if structure else [], timeframe=tf)

    bias_map = bias_engine.get_bias_map(symbol, TIMEFRAMES, structure_map=structure_map, cache=cache)

    # Fix #7C — StructureSnapshot.bias was never assigned anywhere in the
    # live pipeline (StructureEngine.get_snapshot() has no BiasEngine
    # dependency and never sets it), permanently defaulting to "Neutral" --
    # Fix #7B's audit found this made every Strategy plugin reading .bias
    # (via StrategyEngine.to_strategy_snapshot(), which copies
    # structure.bias straight onto StrategySnapshot.bias) unreachable on
    # real bias. bias_map above is already this exact symbol/tf's
    # canonical BiasEngine.evaluate_bias() result (computed one line up,
    # using this same structure_map) -- no new BiasEngine call, no extra
    # candle fetch, no new formula. Populated here rather than inside
    # StructureEngine.get_snapshot() itself: BiasEngine already depends on
    # StructureEngine (via _resolve_structure()), so adding the reverse
    # edge there would create a cycle. Output.py already orchestrates both
    # engines sequentially for every other cross-engine wiring in this
    # function (zones_map -> classify_zones, structure_map -> bias_map
    # itself), so this is the minimal, architecture-preserving point.
    # Read only by to_strategy_snapshot() below -- no other consumer in
    # this file reads structure.bias, so no other V12-core output changes.
    for tf, structure in structure_map.items():
        bias_entry = bias_map.get(tf)
        if bias_entry:
            structure.bias = _canonical_structure_bias(bias_entry["bias_label"])

    prev_bias_map = prev_snapshot.get("bias")

    # --- Scalping ---
    scalping_map = {
        tf: get_style_snapshot(symbol, tf, "scalping", bias_engine, momentum_engine, demand_engine, structure_engine, shift_engine, cache=cache, structure_snapshot=structure_map.get(tf))
        for tf in SCALPING_ORDER
    }
    scalping_alignment = compute_alignment_signal(scalping_map, mode="scalping")
    scalping_history = _update_alignment_history(prev_snapshot, "scalping_alignment_history", scalping_alignment)

    scalping_snapshots_raw = build_scalping_diagnostic(symbol=symbol, scalping_map=scalping_map, bias_map=bias_map, cfg=cfg)
    diagnostic_scalp = scalping_snapshots_raw.get("diagnostic")
    scalping_snapshots = {tf: scalping_snapshots_raw[tf] for tf in SCALPING_ORDER if tf in scalping_snapshots_raw}
    scalping_snapshots = _normalize_snapshot_map(scalping_snapshots)

    # --- Swing ---
    swing_map_raw = {
        tf: get_style_snapshot(symbol, tf, "swing", bias_engine, momentum_engine, demand_engine, structure_engine, shift_engine, cache=cache, structure_snapshot=structure_map.get(tf))
        for tf in SWING_ORDER
    }
    swing_alignment = compute_alignment_signal(swing_map_raw, mode="swing")
    swing_history = _update_alignment_history(prev_snapshot, "swing_alignment_history", swing_alignment)

    swing_map = _normalize_snapshot_map(swing_map_raw)
    swing_snapshots_raw = enrich_swing_with_diagnostic(
        symbol=symbol, swing_map=swing_map, bias_map=bias_map, prev_bias_map=prev_bias_map, cfg=cfg
    )
    diagnostic_swing = swing_snapshots_raw.get("diagnostic")
    swing_snapshots = {tf: swing_snapshots_raw[tf] for tf in SWING_ORDER if tf in swing_snapshots_raw}
    swing_snapshots = _normalize_snapshot_map(swing_snapshots)

    # --- Bias / confidence ---
    bias_ordered = _build_bias_ordered(bias_map)
    bias_conf, momentum_conf, align_conf = _compute_signal_confidence(bias_ordered, scalping_snapshots, scalping_alignment)
    signal_health = compute_signal_health(bias_conf, momentum_conf, align_conf)

    # --- Ordered output blocks ---
    scalping_ordered = OrderedDict(alignment_signal=scalping_alignment, diagnostic=diagnostic_scalp)
    scalping_ordered.update({tf: scalping_snapshots.get(tf, {}) for tf in SCALPING_ORDER})

    swing_ordered = OrderedDict(alignment_signal=swing_alignment, diagnostic=diagnostic_swing)
    swing_ordered.update({tf: swing_snapshots.get(tf, {}) for tf in SWING_ORDER})

    symbol_block = OrderedDict()
    symbol_block["last_updated"] = datetime.now(timezone.utc).isoformat()
    symbol_block["bias"] = bias_ordered
    symbol_block["scalping"] = scalping_ordered
    symbol_block["swing"] = swing_ordered

    clean_block = strip_nulls(symbol_block)
    display_block = add_display_percentages(clean_block, symbol)
    display_block["health"] = build_symbol_health(symbol, display_block)
    display_block["signal_health"] = signal_health

    snr_levels, order_blocks, fvg, swing_points, structure_events = _build_structure_extras(structure_map)
    display_block["strategy_signals"] = _build_strategy_signals(symbol, structure_map)
    display_block["snr_levels"] = snr_levels
    display_block["order_blocks"] = order_blocks
    display_block["fvg"] = fvg
    display_block["swing_points"] = swing_points
    display_block["structure_events"] = structure_events
    display_block["momentum_evidence"] = _build_momentum_evidence(structure_map)
    display_block["supply_demand_zones"] = _build_supply_demand_zones(symbol, demand_engine, cache=cache, zones_map=zones_map, structure_map=structure_map)

    # Cache for next pass (deltas, history, etc.)
    snapshot_cache.set(symbol, {
        "bias": bias_map,
        "scalping": scalping_snapshots,
        "swing": swing_snapshots,
        "scalping_alignment_history": scalping_history,
        "swing_alignment_history": swing_history,
    })

    return display_block


def build_multi_symbol_output(bias_engine, candle_engine, momentum_engine, demand_engine, structure_engine, shift_engine, cache=None, symbols=None) -> dict:
    target_symbols = symbols if symbols else SYMBOLS
    result = {}
    for symbol in target_symbols:
        prev_snapshot = snapshot_cache.get(symbol) or {}
        try:
            result[symbol] = _build_symbol_snapshot(
                symbol, prev_snapshot, bias_engine, candle_engine, momentum_engine, demand_engine, structure_engine, shift_engine, cache=cache
            )
        except Exception as e:
            logger.exception("[%s] snapshot failed", symbol)
            result[symbol] = {"error": str(e)}
    return result