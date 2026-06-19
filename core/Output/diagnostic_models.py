from dataclasses import dataclass
from typing import Any, Dict, Optional

# ---------- Config (tune via DI or env) ----------
@dataclass
class ScalpCfg:
    t_strength_seed: float = 1.5            # M1 strength needed to seed
    t_strength_rising_delta: float = 0.2    # Increase considered "rising"
    t_momentum_min: float = 0.3             # Min momentum for validation
    t_bias_abs_min: float = 0.5             # Ignore tiny bias
    swing_support_strength: float = 1.2     # H1 strength to call "supports long"

# ---------- Helpers for hybrid dict/object access ----------
def get(item: Any, key: str, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)

def label_up(label: Optional[str]) -> bool:
    return (label or "").lower() == "up"

def label_neutral_or_up(label: Optional[str]) -> bool:
    v = (label or "").lower()
    return v in ("neutral", "up")

def flipped_up(prev_label: Optional[str], curr_label: Optional[str]) -> bool:
    prev = (prev_label or "").lower()
    curr = (curr_label or "").lower()
    return prev in ("down", "neutral") and curr == "up"

def normalize_struct_label(lbl: Optional[str]) -> str:
    # Normalize across "Neutral"/"None"/None variants
    if not lbl:
        return "None"
    if lbl.lower() == "neutral":
        return "Neutral"
    return lbl

# ---------- Core enrichment ----------
def enrich_scalping_with_cascade(
    symbol: str,
    scalping_map: Dict[str, Any],               # e.g., M1/M5/M15/M30 StyleSnapshot dicts
    bias_map: Dict[str, Dict[str, Any]],        # per-TF: {label, score, strength}
    prev_bias_map: Optional[Dict[str, Dict[str, Any]]] = None,
    cfg: Optional[ScalpCfg] = None
) -> Dict[str, Any]:
    cfg = cfg or ScalpCfg()

    # Pull current bias + strength from map
    b1, b5, b15 = bias_map.get("M1", {}), bias_map.get("M5", {}), bias_map.get("M15", {})
    s1, s5 = get(b1, "strength", 0.0), get(b5, "strength", 0.0)

    # Previous bias map for flip detection (optional)
    pb5 = get(prev_bias_map.get("M5", {}), "label", None) if prev_bias_map else None

    # From scalping snapshots
    m1_snap = scalping_map.get("M1", {}) or {}
    m5_snap = scalping_map.get("M5", {}) or {}
    m15_snap = scalping_map.get("M15", {}) or {}

    # Momentum (scaled) — if your values are tiny deltas, consider pre-scaling before this step
    m1_mom = float(get(m1_snap, "momentum", 0.0))
    m5_mom = float(get(m5_snap, "momentum", 0.0))

    # Structure/shift/demand/suppression (M5-centric for execution)
    st5 = normalize_struct_label(get(m5_snap, "structure_label", "None"))
    sh5 = bool(get(m5_snap, "shift_confirmed", False))
    dm5 = (get(m5_snap, "demand", "neutral") or "").lower()
    sup1 = bool(get(m1_snap, "suppression", False))
    sup5 = bool(get(m5_snap, "suppression", False))

    # Bias labels
    l1, l5, l15 = get(b1, "label", "neutral"), get(b5, "label", "neutral"), get(b15, "label", "neutral")

    # Checks (atoms)
    checks = {
        "bias_m1_up": label_up(l1),
        "bias_m5_up": label_up(l5),
        "bias_m15_neutral_or_up": label_neutral_or_up(l15),
        "m5_flip_up_on_close": flipped_up(pb5, l5),
        "m1_strength_ok": s1 >= cfg.t_strength_seed,
        "m5_strength_rising": (s5 - (get(prev_bias_map.get("M5", {}), "strength", s5) if prev_bias_map else s5)) >= cfg.t_strength_rising_delta,
        "momentum_ok": (m1_mom >= cfg.t_momentum_min) and (m5_mom >= cfg.t_momentum_min),
        "structure_ok": (st5 in {"BOS", "CHOCH"}) or (st5 == "Neutral" and sh5),
        "shift_ok": sh5,
        "demand_supports": dm5 in {"demand", "strong buy"},
        "suppression": sup1 or sup5
    }

    # Stage + action resolution (M5-centric)
    reasons = []
    if checks["suppression"]:
        stage, action = "Invalidate", "Invalidate"
        reasons.append("Suppression active")
    elif checks["m5_flip_up_on_close"] and checks["m1_strength_ok"]:
        stage, action = "Confirm", "Alert"
        reasons += ["M5 flipped up", "M1 strength supports"]
    elif checks["bias_m1_up"] and checks["bias_m5_up"] and checks["bias_m15_neutral_or_up"]:
        stage, action = "Align", "Prepare"
        reasons += ["M1/M5 aligned", "M15 not against"]
    else:
        if checks["bias_m1_up"] and checks["m1_strength_ok"]:
            stage, action = "Seed", "Watch"
            reasons += ["M1 up with strength"]
        else:
            stage, action = "Seed", "Watch"
            reasons += ["Waiting for M1 seed"]

    # Escalate if validated
    if stage in {"Confirm", "Align"} and checks["momentum_ok"] and checks["structure_ok"]:
        stage, action = "Validate", "Enter"
        reasons += ["Momentum ok", f"Structure ok ({st5})"]
        if checks["shift_ok"]:
            reasons += ["Shift confirmed"]

    # Cascade readiness score (0..1)
    active_flags = [
        checks["bias_m1_up"],
        checks["bias_m5_up"],
        checks["bias_m15_neutral_or_up"],
        checks["m5_flip_up_on_close"],
        checks["m1_strength_ok"],
        checks["m5_strength_rising"],
        checks["momentum_ok"],
        checks["structure_ok"],
        checks["shift_ok"],
        checks["demand_supports"],
    ]
    cascade_score = round(sum(1.0 for f in active_flags if f) / len(active_flags), 2)

    # Alignment summary
    alignment = f"M1:{l1} M5:{l5} M15:{l15}"

    # Swing hint from H1
    h1 = bias_map.get("H1", {})
    h1_label = get(h1, "label", "neutral")
    h1_strength = float(get(h1, "strength", 0.0))

    if label_up(h1_label) and h1_strength >= cfg.swing_support_strength:
        swing_hint = "Swing supports long"
        swing_supports_scalping = True
    elif h1_label.lower() == "neutral":
        swing_hint = "Swing neutral — likely a pullback continuation"
        swing_supports_scalping = False
    else:
        swing_hint = "Swing against — manage as pullback"
        swing_supports_scalping = False

    thresholds = {
        "t_strength_seed": cfg.t_strength_seed,
        "t_strength_rising_delta": cfg.t_strength_rising_delta,
        "t_momentum_min": cfg.t_momentum_min,
        "t_bias_abs_min": cfg.t_bias_abs_min,
        "swing_support_strength": cfg.swing_support_strength,
    }

    node = {
        "stage": stage,
        "action": action,
        "reasons": reasons,
        "alignment": alignment,
        "cascade_score": cascade_score,
        "thresholds": thresholds,
        "checks": checks,
        "timing": {  # placeholder: wire your own bar-age/timestamp deltas if you log flips
            "m5_last_flip_bars": None
        },
        "risk": "High" if checks["suppression"] else ("Low" if cascade_score >= 0.7 else "Medium"),
        "swing_hint": swing_hint,
        "swing_supports_scalping": swing_supports_scalping,
        "version": "scalp_cascade_v1"
    }

    # Attach to each scalping TF (primary logic M5; mirrored node elsewhere for transparency)
    out = {}
    for tf, snap in scalping_map.items():
        # non-destructive copy for dict or object-like
        if isinstance(snap, dict):
            merged = {**snap, "diagnostic": node}
        else:
            # object: attach attribute
            setattr(snap, "diagnostic", node)
            merged = snap
        out[tf] = merged

    return out
