import logging
from dataclasses import asdict
from core.Output.helper import get_previous_state

logger = logging.getLogger(__name__)


def build_scalping_diagnostic(symbol, scalping_map, bias_map, cfg):
    logger.debug("Running scalping diagnostic for %s", symbol)

    # --- Helper functions ---
    def up(label_or_score):
        return label_or_score == "up" or (
            isinstance(label_or_score, (int, float)) and label_or_score > cfg.t_bias_abs_min
        )

    def neutral_or_up(label_or_score):
        return label_or_score in ("neutral", "up") or (
            isinstance(label_or_score, (int, float)) and label_or_score >= 0
        )

    def rising(curr, prev, d=0.2):
        return prev is not None and (curr - prev >= d)

    def flipped_up(prev_label, curr_label):
        return prev_label in ("down", "neutral") and curr_label == "up"

    # --- Previous state (optional) ---
    prev = get_previous_state(symbol)  # from snapshot_cache or DB

    # --- Pull current bias labels & scores ---
    b1_label = bias_map["M1"]["bias_label"]
    b5_label = bias_map["M5"]["bias_label"]
    b15_label = bias_map["M15"]["bias_label"]

    # --- Pull strength from bias_map ---
    s1 = bias_map["M1"]["strength_diagnostic"].strength if bias_map["M1"].get("strength_diagnostic") else None
    s5 = bias_map["M5"]["strength_diagnostic"].strength if bias_map["M5"].get("strength_diagnostic") else None

    # --- Momentum from StyleSnapshot ---
    m1 = scalping_map["M1"].momentum
    m5 = scalping_map["M5"].momentum

    # --- Structure & shift ---
    st5 = scalping_map["M5"].structure_label
    sh5 = scalping_map["M5"].shift_confirmed

    # --- Demand & suppression ---
    demand_label = scalping_map["M5"].demand
    sup1 = getattr(scalping_map["M1"], "suppression", False)
    sup5 = getattr(scalping_map["M5"], "suppression", False)

    # --- Checks ---
    checks = {
        "bias_m1_up": up(b1_label),
        "bias_m5_up": up(b5_label),
        "bias_m15_neutral_or_up": neutral_or_up(b15_label),
        "m5_flip_up_on_close": flipped_up(
            prev["bias"]["M5"]["bias_label"] if prev else None,
            b5_label
        ),
        "m1_strength_ok": s1 is not None and s1 >= cfg.t_strength_seed,
        "m5_strength_rising": (
            s5 is not None and rising(
                s5,
                prev["bias"]["M5"]["strength_diagnostic"].strength
                if prev and prev["bias"]["M5"].get("strength_diagnostic") else None,
                cfg.t_strength_rising_delta
            )
        ),
        "momentum_ok": m1 >= cfg.t_momentum_min and m5 >= cfg.t_momentum_min,
        "structure_ok": st5 in {"BOS", "CHOCH"} or (st5 == "Neutral" and sh5),
        "shift_ok": bool(sh5),
        "demand_supports": demand_label in {"demand", "strong buy"},
        "suppression": sup1 or sup5,
    }


    # Stage + action resolution (M5-centric)
    # ✅ Initialize first
    stage = None
    action = None
    reasons = []

    # ✅ Then your logic
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

    # ✅ Final fallback (optional but safe)
    if stage is None:
        stage = "Seed"
        action = "Watch"
        reasons.append("Fallback: no matching condition")


    # Escalate to Validate/Execute if strong
    if stage in {"Confirm", "Align"} and checks["momentum_ok"] and checks["structure_ok"]:
        stage, action = "Validate", "Enter"
        reasons += ["Momentum ok", f"Structure ok ({st5})"]
        if checks["shift_ok"]:
            reasons += ["Shift confirmed"]

        
    # ✅ Build summary based on stage and reasons
    if stage == "Validate":
        if "M5 flipped up" in reasons and "M1 strength supports" in reasons:
            summary = "Scalping long confirmed — M5 flipped up, M1 strength supports, momentum and structure aligned"
        elif "M1/M5 aligned" in reasons:
            summary = "Scalping bias aligning — M1/M5 bias up, M15 neutral, momentum and structure aligned"
        else:
            summary = "Scalping long confirmed — momentum and structure aligned"
        if checks["shift_ok"]:
            summary += ", shift confirmed"
    elif stage == "Confirm":
        summary = "Scalping signal forming — M5 flipped up, M1 strength supports"
    elif stage == "Align":
        summary = "Scalping bias aligning — M1/M5 bias up, M15 neutral"
    elif stage == "Seed":
        summary = "Scalping setup forming — waiting for bias and strength"
    elif stage == "Invalidate":
        summary = "Scalping invalidated — suppression or conflicting bias"
    else:
        summary = "Scalping setup unclear — monitoring conditions"

        
    if not stage:
        stage = "Seed"
        action = "Watch"
        reasons.append("Fallback: no matching condition")
        logger.debug("Summary built: %s", summary)

                
    # Cascade score (0..1) — simple blend; tune as needed
    cascade_score = float(sum([
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
    ])) / 10.0

    # Alignment summary
    alignment = f"M1:{b1_label} M5:{b5_label} M15:{b15_label}"
    

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
        "cascade_score": round(cascade_score, 2),
        "thresholds": thresholds,
        "checks": checks,
        "timing": {
            "m5_last_flip_bars": None
        },
        "risk": "High" if checks["suppression"] else ("Low" if cascade_score >= 0.7 else "Medium"),
        "summary": summary,
        "version": "scalp_cascade_v1"
    }

    tf_data = {tf: asdict(scalping_map[tf]) for tf in ["M1", "M5", "M15", "M30"]}

    return {
        "diagnostic": node,
        **tf_data
    }

    


