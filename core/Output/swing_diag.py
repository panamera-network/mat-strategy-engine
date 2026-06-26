from dataclasses import asdict
from typing import Any, Dict, Optional

from core.Output.diagnostic_models import ScalpCfg, flipped_up, get, label_neutral_or_up, label_up, normalize_struct_label


def _bias_strength(bias_entry: Dict[str, Any]) -> float:
    diag = get(bias_entry, "strength_diagnostic", None)
    return diag.strength if diag else 0.0


def enrich_swing_with_diagnostic(
    symbol: str,
    swing_map: Dict[str, Any],
    bias_map: Dict[str, Dict[str, Any]],
    prev_bias_map: Optional[Dict[str, Dict[str, Any]]] = None,
    cfg: Optional[ScalpCfg] = None
) -> Dict[str, Any]:
    cfg = cfg or ScalpCfg()

    # Pull bias + strength
    b_h1, b_h4, b_d1 = bias_map.get("H1", {}), bias_map.get("H4", {}), bias_map.get("D1", {})
    s_h1, s_h4, s_d1 = _bias_strength(b_h1), _bias_strength(b_h4), _bias_strength(b_d1)

    # Previous labels
    pb_h4 = get(prev_bias_map.get("H4", {}), "bias_label", None) if prev_bias_map else None

    # Labels
    l_h1, l_h4, l_d1 = get(b_h1, "bias_label", "neutral"), get(b_h4, "bias_label", "neutral"), get(b_d1, "bias_label", "neutral")

    # Snapshots
    h1_snap = swing_map.get("H1", {}) or {}
    h4_snap = swing_map.get("H4", {}) or {}
    d1_snap = swing_map.get("D1", {}) or {}

    # Structure/shift/demand/suppression
    st_h4 = normalize_struct_label(get(h4_snap, "structure_label", "None"))
    sh_h4 = bool(get(h4_snap, "shift_confirmed", False))
    dm_h4 = (get(h4_snap, "demand", "neutral") or "").lower()
    sup_h1 = bool(get(h1_snap, "suppression", False))
    sup_h4 = bool(get(h4_snap, "suppression", False))

    # Momentum
    m_h1 = float(get(h1_snap, "momentum", 0.0))
    m_h4 = float(get(h4_snap, "momentum", 0.0))

    # Checks
    checks = {
        "bias_h1_up": label_up(l_h1),
        "bias_h4_up": label_up(l_h4),
        "bias_d1_neutral_or_up": label_neutral_or_up(l_d1),
        "h4_flip_up": flipped_up(pb_h4, l_h4),
        "h1_strength_ok": s_h1 >= cfg.t_strength_seed,
        "h4_strength_rising": (s_h4 - (_bias_strength(prev_bias_map.get("H4", {})) if prev_bias_map else s_h4)) >= cfg.t_strength_rising_delta,
        "momentum_ok": m_h1 >= cfg.t_momentum_min and m_h4 >= cfg.t_momentum_min,
        "structure_ok": st_h4 in {"BOS", "CHOCH"} or (st_h4 == "Neutral" and sh_h4),
        "shift_ok": sh_h4,
        "demand_supports": dm_h4 in {"demand", "strong buy"},
        "suppression": sup_h1 or sup_h4
    }

    # Stage + action
    stage = "Seed"
    action = "Watch"
    reasons = []
    
    if checks["suppression"]:
        stage, action = "Invalidate", "Invalidate"
        reasons.append("Suppression active")
    elif checks["bias_h1_up"] and checks["h1_strength_ok"]:
        stage, action = "Seed", "Watch"
        reasons.append("H1 bias up with strength")
    elif checks["h4_flip_up"] and checks["h4_strength_rising"]:
        stage, action = "Confirm", "Alert"
        reasons += ["H4 flipped up", "H4 strength rising"]
    elif checks["bias_h1_up"] and checks["bias_h4_up"] and checks["bias_d1_neutral_or_up"]:
        stage, action = "Align", "Prepare"
        reasons += ["H1/H4 aligned", "D1 not against"]
    else:
        # Even if no escalation, explain why
        if not checks["bias_h1_up"]:
            reasons.append("H1 bias not up")
        if not checks["h1_strength_ok"]:
            reasons.append("H1 strength below threshold")
        if not checks["bias_h4_up"]:
            reasons.append("H4 bias not up")
        if not checks["h4_strength_rising"]:
            reasons.append("H4 strength not rising")
        if not checks["momentum_ok"]:
            reasons.append("Momentum not sufficient")
        if not checks["shift_ok"]:
            reasons.append("No confirmed shift")
        if not checks["demand_supports"]:
            reasons.append("Demand zone not supportive")

    if stage == "Validate":
        summary = "Swing long confirmed — bias and structure aligned"
    elif stage == "Align":
        summary = "Swing bias aligning — H1/H4 bias up, D1 supportive"
    elif stage == "Seed":
        summary = "Swing setup forming — waiting for H1 strength and structure"
    elif stage == "Invalidate":
        summary = "Swing invalidated — suppression or conflicting bias"
    else:
        summary = "Swing setup unclear — monitoring conditions"


    # Conviction score
    active_flags = list(checks.values())
    conviction_score = round(sum(1.0 for f in active_flags if f) / len(active_flags), 2)

    alignment = f"H1:{h1_snap['direction']} {h1_snap['structure_label']} | " \
            f"H4:{h4_snap['direction']} {h4_snap['structure_label']} | " \
            f"D1:{d1_snap['direction']} {d1_snap['structure_label']}"

    thresholds = {
        "t_strength_seed": cfg.t_strength_seed,
        "t_strength_rising_delta": cfg.t_strength_rising_delta,
        "t_momentum_min": cfg.t_momentum_min,
        "t_bias_abs_min": cfg.t_bias_abs_min,
        "swing_support_strength": cfg.swing_support_strength

    }

    node = {
        "stage": stage,
        "action": action,
        "reasons": reasons,
        "alignment": alignment,
        "conviction_score": conviction_score,
        "thresholds": thresholds,
        "checks": checks,
        "risk": "High" if checks["suppression"] else ("Low" if conviction_score >= 0.7 else "Medium"),
        "summary": summary,
        "version": "swing_diagnostic_v1"
    }

    # Build TF data without embedding diagnostic in each
    tf_data = {}
    for tf, snap in swing_map.items():
        if isinstance(snap, dict):
            tf_data[tf] = snap
        else:
            tf_data[tf] = asdict(snap)  # or snap.__dict__ if not a dataclass

    # Return top-level diagnostic + TFs
    return {
        "diagnostic": node,
        **tf_data
    }

