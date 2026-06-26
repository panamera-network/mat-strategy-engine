import logging
from core.Output.alignment_signal import compute_alignment_signal, compute_signal_health
from core.Output.build_scalping import build_scalping_diagnostic
from core.Output.diagnostic_models import ScalpCfg
from core.Output.health_log import build_symbol_health
from core.Output.helper import add_display_percentages, confidence_color, strip_nulls

from core.Output.swing_diag import enrich_swing_with_diagnostic
from core.SnapshotCache import SnapshotCache
from core.StyleEngine import get_style_snapshot
from core.core_models import StrengthDiagnostic
from mt5.constants import SYMBOLS, TIMEFRAMES
from collections import OrderedDict
from datetime import datetime

# Initialize snapshot cache
snapshot_cache = SnapshotCache()

# Diagnostic config
cfg = ScalpCfg(
    t_strength_seed=1.5,
    t_strength_rising_delta=0.2,
    t_momentum_min=0.3,
    t_bias_abs_min=0.5,
    swing_support_strength=1.2
)

SCALPING_TFS = ["M1", "M5", "M15", "M30"]
SWING_TFS = [tf for tf in TIMEFRAMES if tf not in SCALPING_TFS]


# Timeframe orders
BIAS_ORDER = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
SCALPING_ORDER = ["M1", "M5", "M15", "M30"]
SWING_ORDER = ["H1", "H4", "D1", "W1", "MN1"]

logging.basicConfig(
    level=logging.INFO,  # show INFO and above
    format="%(levelname)s:%(message)s"
)

# --- Main builder ---
def build_multi_symbol_output(
    bias_engine,
    candle_engine,
    momentum_engine,
    demand_engine,
    structure_engine,
    shift_engine
):
    result = {}

    for symbol in SYMBOLS:
        try:
            bias_map = bias_engine.get_bias_map(symbol, TIMEFRAMES)
            prev_snapshot = snapshot_cache.get(symbol) or {}
            prev_bias_map = prev_snapshot.get("bias")

            # --- Scalping ---
            scalping_map = {
                tf: get_style_snapshot(symbol, tf, "scalping",
                                       bias_engine, momentum_engine,
                                       demand_engine, structure_engine, shift_engine)
                for tf in SCALPING_ORDER
            }
            scalping_alignment = compute_alignment_signal(scalping_map, mode="scalping")

            # Track scalping alignment history
            scalping_history = prev_snapshot.get("scalping_alignment_history", [])
            scalping_history.append(scalping_alignment["confidence_pct"])
            scalping_history = scalping_history[-10:]
            scalping_alignment["confidence_history"] = scalping_history

            scalping_snapshots = build_scalping_diagnostic(
                symbol=symbol,
                scalping_map=scalping_map,
                bias_map=bias_map,
                cfg=cfg
            )

            for tf, snap in scalping_snapshots.items():
                snap_dict = snap.__dict__.copy() if hasattr(snap, "__dict__") else dict(snap)
                if "demand" in snap_dict:
                    snap_dict["zone"] = snap_dict.pop("demand")
                if "checks" in snap_dict and "demand_supports" in snap_dict["checks"]:
                    snap_dict["checks"]["zone_supports"] = snap_dict["checks"].pop("demand_supports")
                if "conviction_breakdown" in snap_dict and "demand" in snap_dict["conviction_breakdown"]:
                    snap_dict["conviction_breakdown"]["zone_score"] = snap_dict["conviction_breakdown"].pop("demand")
                if "momentum" in snap_dict:
                    snap_dict["momentum"] = float(f"{snap_dict['momentum']:.4f}")
                    abs_val = abs(snap_dict["momentum"])
                    if abs_val < 0.2:
                        snap_dict["momentum_band"] = "weak"
                    elif abs_val < 0.5:
                        snap_dict["momentum_band"] = "moderate"
                    else:
                        snap_dict["momentum_band"] = "strong"
                    max_momentum = 2.0
                    pct = abs_val / max_momentum * 100
                    snap_dict["momentum_color"] = confidence_color(pct)
                scalping_snapshots[tf] = snap_dict

            # --- Swing ---
            swing_map_raw = {
                tf: get_style_snapshot(symbol, tf, "swing",
                                       bias_engine, momentum_engine,
                                       demand_engine, structure_engine, shift_engine)
                for tf in SWING_ORDER
            }
            swing_alignment = compute_alignment_signal(swing_map_raw, mode="swing")

            # Track swing alignment history
            swing_history = prev_snapshot.get("swing_alignment_history", [])
            swing_history.append(swing_alignment["confidence_pct"])
            swing_history = swing_history[-10:]
            swing_alignment["confidence_history"] = swing_history

            swing_map = {tf: s.__dict__.copy() if hasattr(s, "__dict__") else dict(s) for tf, s in swing_map_raw.items()}

            swing_snapshots = enrich_swing_with_diagnostic(
                symbol=symbol,
                swing_map=swing_map,
                bias_map=bias_map,
                prev_bias_map=prev_bias_map,
                cfg=cfg
            )

            for tf, snap in swing_snapshots.items():
                snap_dict = snap.__dict__.copy() if hasattr(snap, "__dict__") else dict(snap)
                if "demand" in snap_dict:
                    snap_dict["zone"] = snap_dict.pop("demand")
                if "checks" in snap_dict and "demand_supports" in snap_dict["checks"]:
                    snap_dict["checks"]["zone_supports"] = snap_dict["checks"].pop("demand_supports")
                if "conviction_breakdown" in snap_dict and "demand" in snap_dict["conviction_breakdown"]:
                    snap_dict["conviction_breakdown"]["zone_score"] = snap_dict["conviction_breakdown"].pop("demand")
                if "momentum" in snap_dict:
                    snap_dict["momentum"] = float(f"{snap_dict['momentum']:.4f}")
                    abs_val = abs(snap_dict["momentum"])
                    if abs_val < 0.2:
                        snap_dict["momentum_band"] = "weak"
                    elif abs_val < 0.5:
                        snap_dict["momentum_band"] = "moderate"
                    else:
                        snap_dict["momentum_band"] = "strong"
                    max_momentum = 2.0
                    pct = abs_val / max_momentum * 100
                    snap_dict["momentum_color"] = confidence_color(pct)
                swing_snapshots[tf] = snap_dict

            # --- Bias ordered ---
            bias_ordered = OrderedDict()
            for tf in BIAS_ORDER:
                score_val = bias_map.get(tf, {}).get("bias_score")
                strength_val = (
                    bias_map.get(tf, {}).get("strength_diagnostic").strength
                    if isinstance(bias_map.get(tf, {}).get("strength_diagnostic"), StrengthDiagnostic)
                    else None
                )
                bias_ordered[tf] = {
                    "label": bias_map.get(tf, {}).get("bias_label"),
                    "score": score_val,
                    "strength": strength_val
                }
                if score_val is not None:
                    max_bias = 4.0
                    pct = abs(score_val) / max_bias * 100
                    bias_ordered[tf]["score_color"] = confidence_color(pct)

            # --- Confidence for signal health ---
            bias_conf = 0
            bias_scores = [v["score"] for v in bias_ordered.values() if v.get("score") is not None]
            if bias_scores:
                max_bias = 4.0
                bias_conf = round(sum(abs(s) / max_bias * 100 for s in bias_scores) / len(bias_scores), 1)

            momentum_conf = 0
            mom_vals = []
            for tf in SCALPING_ORDER:
                val = scalping_snapshots.get(tf, {}).get("momentum")
                if val is not None:
                    mom_vals.append(abs(val) / 2.0 * 100)
            if mom_vals:
                momentum_conf = round(sum(mom_vals) / len(mom_vals), 1)

            align_conf = scalping_alignment["confidence_pct"] if scalping_alignment else 0
            signal_health = compute_signal_health(bias_conf, momentum_conf, align_conf)

            # --- Ordered scalping ---
            scalping_ordered = OrderedDict()
            scalping_ordered["alignment_signal"] = scalping_alignment
            scalping_ordered["diagnostic"] = scalping_snapshots["diagnostic"]
            for tf in SCALPING_ORDER:
                scalping_ordered[tf] = scalping_snapshots.get(tf, {})

            # --- Ordered swing ---
            swing_ordered = OrderedDict()
            swing_ordered["alignment_signal"] = swing_alignment
            swing_ordered["diagnostic"] = swing_snapshots["diagnostic"]
            for tf in SWING_ORDER:
                swing_ordered[tf] = swing_snapshots.get(tf, {})

            # --- Final block ---
            symbol_block = OrderedDict()
            symbol_block["last_updated"] = datetime.utcnow().isoformat() + "Z"
            symbol_block["bias"] = bias_ordered
            symbol_block["scalping"] = scalping_ordered
            symbol_block["swing"] = swing_ordered

            clean_block = strip_nulls(symbol_block)
            display_block = add_display_percentages(clean_block, symbol)
            health_data = build_symbol_health(symbol, display_block)
            display_block["health"] = health_data
            display_block["signal_health"] = signal_health

            result[symbol] = display_block

            # Cache updated snapshot
            snapshot_cache.set(symbol, {
                "bias": bias_map,
                "scalping": scalping_snapshots,
                "swing": swing_snapshots,
                "scalping_alignment_history": scalping_history,
                "swing_alignment_history": swing_history
            })

        except Exception as e:
            result[symbol] = {"error": str(e)}
            print(f"[{symbol}] snapshot failed: {e}")

    return result
