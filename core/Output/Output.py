import logging
from dataclasses import asdict
from datetime import datetime, timezone
from collections import OrderedDict

from core.Output.alignment_signal import compute_alignment_signal, compute_signal_health
from core.Output.build_scalping import build_scalping_diagnostic
from core.Output.diagnostic_models import cfg, BIAS_ORDER, SCALPING_ORDER, SWING_ORDER
from core.Output.health_log import build_symbol_health
from core.Output.helper import add_display_percentages, confidence_color, strip_nulls
from core.Output.swing_diag import enrich_swing_with_diagnostic
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
MAX_MOMENTUM = 2.0
MAX_BIAS = 4.0
MOMENTUM_BAND_WEAK = 0.2
MOMENTUM_BAND_MODERATE = 0.5
ALIGNMENT_HISTORY_LIMIT = 10


def _momentum_band(abs_momentum: float) -> str:
    if abs_momentum < MOMENTUM_BAND_WEAK:
        return "weak"
    if abs_momentum < MOMENTUM_BAND_MODERATE:
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

    checks = snap_dict.get("checks")
    if checks and "demand_supports" in checks:
        checks["zone_supports"] = checks.pop("demand_supports")

    breakdown = snap_dict.get("conviction_breakdown")
    if breakdown and "demand" in breakdown:
        breakdown["zone_score"] = breakdown.pop("demand")

    if "momentum" in snap_dict:
        momentum = float(f"{snap_dict['momentum']:.4f}")
        snap_dict["momentum"] = momentum
        abs_val = abs(momentum)
        snap_dict["momentum_band"] = _momentum_band(abs_val)
        pct = abs_val / MAX_MOMENTUM * 100
        snap_dict["momentum_color"] = confidence_color(pct)

    return snap_dict


def _normalize_snapshot_map(snapshot_map: dict) -> dict:
    return {tf: _normalize_snapshot(snap) for tf, snap in snapshot_map.items()}


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

        bias_ordered[tf] = {
            "label": tf_data.get("bias_label"),
            "score": score_val,
            "strength": strength_val,
        }
        if score_val is not None:
            pct = abs(score_val) / MAX_BIAS * 100
            bias_ordered[tf]["score_color"] = confidence_color(pct)
    return bias_ordered


def _compute_signal_confidence(bias_ordered: dict, scalping_snapshots: dict, scalping_alignment: dict) -> tuple:
    bias_scores = [v["score"] for v in bias_ordered.values() if v.get("score") is not None]
    bias_conf = round(sum(abs(s) / MAX_BIAS * 100 for s in bias_scores) / len(bias_scores), 1) if bias_scores else 0

    mom_vals = [
        abs(scalping_snapshots[tf]["momentum"]) / MAX_MOMENTUM * 100
        for tf in SCALPING_ORDER
        if scalping_snapshots.get(tf, {}).get("momentum") is not None
    ]
    momentum_conf = round(sum(mom_vals) / len(mom_vals), 1) if mom_vals else 0

    align_conf = scalping_alignment["confidence_pct"] if scalping_alignment else 0
    return bias_conf, momentum_conf, align_conf


def _build_structure_context(symbol: str, structure_engine, cache=None) -> dict:
    """Fetch one raw StructureSnapshot per timeframe — single source for
    strategy evaluation, SNR levels, order blocks, and FVGs below, so we
    don't re-fetch structure data per feature."""
    structure_map = {}
    for tf in BIAS_ORDER:
        structure = structure_engine.get_snapshot(symbol, tf, cache=cache)
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
    """Per-timeframe SNR levels, order blocks, and FVGs as plain dicts."""
    snr_levels = {tf: [asdict(lvl) for lvl in s.snr_levels] for tf, s in structure_map.items() if s.snr_levels}
    order_blocks = {tf: [asdict(ob) for ob in s.order_blocks] for tf, s in structure_map.items() if s.order_blocks}
    fvg = {tf: [asdict(f) for f in s.fvg] for tf, s in structure_map.items() if s.fvg}
    return snr_levels, order_blocks, fvg


def _build_supply_demand_zones(symbol: str, demand_engine, cache=None) -> dict:
    zones = {}
    for tf in BIAS_ORDER:
        tf_zones = [asdict(z) for z in demand_engine.get_zones(symbol, tf, cache=cache) if z.valid]
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
    bias_map = bias_engine.get_bias_map(symbol, TIMEFRAMES, cache=cache)
    prev_bias_map = prev_snapshot.get("bias")

    # --- Scalping ---
    scalping_map = {
        tf: get_style_snapshot(symbol, tf, "scalping", bias_engine, momentum_engine, demand_engine, structure_engine, shift_engine, cache=cache)
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
        tf: get_style_snapshot(symbol, tf, "swing", bias_engine, momentum_engine, demand_engine, structure_engine, shift_engine, cache=cache)
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

    structure_map = _build_structure_context(symbol, structure_engine, cache=cache)
    snr_levels, order_blocks, fvg = _build_structure_extras(structure_map)
    display_block["strategy_signals"] = _build_strategy_signals(symbol, structure_map)
    display_block["snr_levels"] = snr_levels
    display_block["order_blocks"] = order_blocks
    display_block["fvg"] = fvg
    display_block["supply_demand_zones"] = _build_supply_demand_zones(symbol, demand_engine, cache=cache)

    # Cache for next pass (deltas, history, etc.)
    snapshot_cache.set(symbol, {
        "bias": bias_map,
        "scalping": scalping_snapshots,
        "swing": swing_snapshots,
        "scalping_alignment_history": scalping_history,
        "swing_alignment_history": swing_history,
    })

    return display_block


def build_multi_symbol_output(bias_engine, candle_engine, momentum_engine, demand_engine, structure_engine, shift_engine, cache=None) -> dict:
    result = {}
    for symbol in SYMBOLS:
        prev_snapshot = snapshot_cache.get(symbol) or {}
        try:
            result[symbol] = _build_symbol_snapshot(
                symbol, prev_snapshot, bias_engine, candle_engine, momentum_engine, demand_engine, structure_engine, shift_engine, cache=cache
            )
        except Exception as e:
            logger.exception("[%s] snapshot failed", symbol)
            result[symbol] = {"error": str(e)}
    return result