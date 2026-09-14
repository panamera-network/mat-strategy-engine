import logging
from typing import Any, Dict, Optional
from core.Output.diagnostic_models import cfg, BIAS_ORDER, SCALPING_ORDER, SWING_ORDER
from core.SnapshotCache import snapshot_cache

def get_previous_state(symbol: str) -> Optional[Dict[str, Any]]:
    return snapshot_cache.get(symbol)

def strip_nulls(obj):
    if isinstance(obj, dict):
        return {k: strip_nulls(v) for k, v in obj.items() if v is not None or isinstance(v, (dict, list))}
    elif isinstance(obj, list):
        return [strip_nulls(v) for v in obj if v is not None or isinstance(v, (dict, list))]
    return obj

# Central place to define theoretical max values with overrides
# Fix #6AD — the per-mode "momentum" entries formerly here (default: 1.0,
# scalping: 50.0, swing: 2000.0) were removed: momentum_pct/momentum_color
# now source MOMENTUM_PCT_ATR_REFERENCE below instead (Fix #6AC), and the
# default entry was already unreferenced before that (get_display_max()
# is only ever called with mode "bias"/"scalping"/"swing", and the bias
# path never read a momentum value at all). Confirmed zero remaining
# consumers via repo-wide grep before removal.
display_max_config = {
    "default": {
        "bias_score": 4.0,
        "strength": getattr(cfg, "strength_max", 10.0),
        "score": 1.0
    },
    "scalping": {
    },
    "swing": {
    },
    "symbol_overrides": {

    }
}

# Fix #6AC — presentation reference/cap for live momentum_pct/momentum_color
# (scheme C, add_display_percentages() below), in ATR units. Not a physical
# maximum (atr_normalized_momentum itself is unclamped, see
# MomentumEngine.py) -- just the point at which momentum_pct saturates to
# +/-100%. Replaces the old per-mode display_max_config["scalping"/"swing"]
# ["momentum"] (50.0/2000.0) split, removed by Fix #6AD -- those were tuned
# against the legacy raw, per-instrument-scale-dependent momentum score and
# required two different constants for the same concept; a single
# canonical ATR reference needs only one, shared by both scalping and
# swing. Kept as its own named constant, distinct from Output.py's
# MOMENTUM_CONF_ATR_REFERENCE (Fix #6AB's momentum_conf) -- same numeric
# value today, separate presentation paths.
MOMENTUM_PCT_ATR_REFERENCE = 2.0


def get_display_max(symbol: str, mode: str) -> Dict[str, float]:
    max_vals = dict(display_max_config["default"])
    if mode in display_max_config:
        max_vals.update(display_max_config[mode])
    if symbol in display_max_config.get("symbol_overrides", {}):
        max_vals.update(display_max_config["symbol_overrides"][symbol])
    return max_vals

def scale_to_pct(value, max_value, min_value=0.0):
    if value is None:
        return None
    if not max_value:
        return 0.0
    clamped = max(min(value, max_value), min_value)
    pct = round((clamped / max_value) * 100, 2)
    return 0.0 if pct == -0.0 else pct


def pct_to_color(pct, directional=True):
    """Convert a percentage to a hex color string."""
    if pct is None:
        return None
    if directional:
        if pct > 0:
            intensity = int((pct / 100) * 255)
            return f"#00{intensity:02X}00"  # green fade
        elif pct < 0:
            intensity = int((abs(pct) / 100) * 255)
            return f"#{intensity:02X}0000"  # red fade
        else:
            return "#CCCCCC"  # neutral grey
    else:
        intensity = int((pct / 100) * 255)
        return f"#00{intensity:02X}00"  # green fade only

def add_display_percentages(symbol_block, symbol):
    # Bias section
    bias_max = get_display_max(symbol, "bias")
    for tf, vals in symbol_block["bias"].items():
        pct = scale_to_pct(vals.get("score"), bias_max["bias_score"], -bias_max["bias_score"])
        vals["score_pct"] = pct
        vals["score_color"] = pct_to_color(pct, directional=True)

        spct = scale_to_pct(vals.get("strength"), bias_max["strength"], 0.0)
        vals["strength_pct"] = spct
        vals["strength_color"] = pct_to_color(spct, directional=False)

    # Scalping diagnostic
    scalping_max = get_display_max(symbol, "scalping")
    diag = symbol_block["scalping"]["diagnostic"]
    spct = scale_to_pct(diag.get("score"), scalping_max["score"], 0.0)
    diag["score_pct"] = spct
    diag["score_color"] = pct_to_color(spct, directional=False)

    # Swing diagnostic
    swing_max = get_display_max(symbol, "swing")
    diag = symbol_block["swing"]["diagnostic"]
    spct = scale_to_pct(diag.get("score"), swing_max["score"], 0.0)
    diag["score_pct"] = spct
    diag["score_color"] = pct_to_color(spct, directional=False)

    # Scalping TF snapshots
    for tf in SCALPING_ORDER:
        snap = symbol_block["scalping"].get(tf)
        if snap:
            # Fix #6AC — momentum_pct/momentum_color now source canonical
            # atr_normalized_momentum against a single shared ATR reference,
            # not the legacy raw `momentum` scaled against a scalping-only
            # max. Signed, unlike Fix #6AB's momentum_conf -- direction is
            # this pair's whole display purpose (pct_to_color(directional=True)
            # below is unchanged).
            mpct = scale_to_pct(snap.get("atr_normalized_momentum"), MOMENTUM_PCT_ATR_REFERENCE, -MOMENTUM_PCT_ATR_REFERENCE)
            snap["momentum_pct"] = mpct
            snap["momentum_color"] = pct_to_color(mpct, directional=True)

            bpct = scale_to_pct(snap.get("bias"), scalping_max["bias_score"], -scalping_max["bias_score"])
            snap["bias_pct"] = bpct
            snap["bias_color"] = pct_to_color(bpct, directional=True)

    # Swing TF snapshots
    for tf in SWING_ORDER:
        snap = symbol_block["swing"].get(tf)
        if snap:
            # Fix #6AC — same canonical ATR reference as scalping above; no
            # separate scalping/swing momentum scale any more.
            mpct = scale_to_pct(snap.get("atr_normalized_momentum"), MOMENTUM_PCT_ATR_REFERENCE, -MOMENTUM_PCT_ATR_REFERENCE)
            snap["momentum_pct"] = mpct
            snap["momentum_color"] = pct_to_color(mpct, directional=True)

            bpct = scale_to_pct(snap.get("bias"), swing_max["bias_score"], -swing_max["bias_score"])
            snap["bias_pct"] = bpct
            snap["bias_color"] = pct_to_color(bpct, directional=True)

    return symbol_block


def confidence_color(conf_pct: float) -> str:
    if conf_pct >= 75:
        return "#009900"  # strong green
    elif conf_pct >= 50:
        return "#CCCC00"  # amber
    elif conf_pct >= 25:
        return "#FF8800"  # orange
    else:
        return "#CC0000"  # red
