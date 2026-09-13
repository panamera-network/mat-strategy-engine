from core.Output.helper import confidence_color
from core.SnapshotCache import SnapshotCache

snapshot_cache = SnapshotCache

def compute_alignment_signal(tf_snapshots: dict, mode: str) -> dict:
    tf_map = {
        "scalping": ["M1", "M5", "M15", "M30"],
        "swing": ["H1", "H4", "D1", "W1", "MN1"]
    }
    selected_tfs = tf_map[mode]

    # Weighting
    if mode == "swing":
        weights = {"H1": 1.0, "H4": 1.5, "D1": 2.0, "W1": 2.5, "MN1": 3.0}
    else:
        weights = {tf: 1.0 for tf in selected_tfs}

    total_score = 0
    breakdown = {}
    # Fix #6G — two contributors per tf (direction, momentum), so this stays
    # sum(abs(w) * 2 ...) — correct again now that zone interaction no
    # longer votes below (it never should have counted as a third ±1
    # contributor here; see Fix #6F's audit).
    max_possible = sum(abs(w) * 2 for w in weights.values())

    for tf in selected_tfs:
        snap = tf_snapshots.get(tf)
        if not snap:
            breakdown[tf] = None
            continue

        # Fix #6AF — momentum vote now sources canonical
        # atr_normalized_momentum instead of the legacy raw StyleSnapshot
        # .momentum (Fix #6AE's audit found the legacy +/-0.3 threshold on
        # the raw price-scale field never fired for standard FX (0.0%
        # activation) while firing on 86-94% of metals/crypto readings --
        # a scale defect, not a real difference in momentum behavior). The
        # legacy `momentum` field itself is no longer read here at all.
        if hasattr(snap, "direction"):
            direction = snap.direction
            atr_momentum = getattr(snap, "atr_normalized_momentum", None)
        elif isinstance(snap, dict):
            direction = snap.get("direction")
            atr_momentum = snap.get("atr_normalized_momentum")
        else:
            snap = snap.__dict__.copy()
            direction = snap.get("direction")
            atr_momentum = snap.get("atr_normalized_momentum")

        score = 0
        if direction in ["uptrend", "bullish"]:
            score += 1
        elif direction in ["downtrend", "bearish"]:
            score -= 1

        # Fix #6AF — +/-1.0 ATR is the "strong momentum" threshold locked
        # by Fix #6Z's canonical bands (Fix #6AE's audit, Q7): strict >/<
        # so exactly +/-1.0 ATR itself stays neutral, matching the prior
        # strict-comparison convention. None (canonical value unavailable)
        # casts no momentum vote at all -- never guessed as neutral-by-
        # coincidence versus genuinely absent.
        if atr_momentum is not None:
            if atr_momentum > 1.0:
                score += 1
            elif atr_momentum < -1.0:
                score -= 1

        # Fix #6G — zone interaction (legacy shift_confirmed/shift_direction,
        # canonical zone_interaction/zone_interaction_direction) no longer
        # contributes to this score (Fix #6F's audit: a mere price/zone
        # touch was voting equally with bias and momentum, and could single-
        # handedly cross the Go Long/Go Short threshold on higher-weighted
        # swing timeframes). It remains fully observable elsewhere — every
        # per-tf StyleSnapshot in /core/output already carries
        # zone_interaction/zone_interaction_direction/zone_interaction_color
        # (Fix #6D) alongside the legacy shift_* aliases — so nothing is
        # lost, it simply no longer votes on this decision.

        weighted_score = score * weights[tf]
        breakdown[tf] = round(weighted_score, 2)
        total_score += weighted_score

    if total_score >= 3:
        decision = "Go Long"
    elif total_score <= -3:
        decision = "Go Short"
    else:
        decision = "Stand Aside"

    confidence_pct = round(abs(total_score) / max_possible * 100, 1)
    summary = build_alignment_summary(breakdown, mode, decision, confidence_pct)

    return {
        "decision": decision,
        "total_score": round(total_score, 2),
        "confidence_pct": confidence_pct,
        "confidence_color": confidence_color(confidence_pct),
        "summary": summary,
        "breakdown": breakdown
    }


def build_alignment_summary(breakdown: dict, mode: str, decision: str, confidence_pct: float) -> str:
    positives = [tf for tf, score in breakdown.items() if score and score > 0]
    negatives = [tf for tf, score in breakdown.items() if score and score < 0]
    neutrals  = [tf for tf, score in breakdown.items() if score == 0 or score is None]

    # Weight map for importance
    tf_weights = {
        "M1": 1, "M5": 1, "M15": 1, "M30": 1,
        "H1": 1, "H4": 2, "D1": 3, "W1": 4, "MN1": 5
    }

    parts = []

    # Core bias description
    if positives and not negatives and not neutrals:
        parts.append(f"All {mode} timeframes bullish")
    elif negatives and not positives and not neutrals:
        parts.append(f"All {mode} timeframes bearish")
    elif positives and not negatives:
        parts.append(f"{mode.capitalize()} bias bullish")
    elif negatives and not positives:
        parts.append(f"{mode.capitalize()} bias bearish")
    elif positives and negatives:
        high_tf_pos = any(tf in positives and tf_weights[tf] >= 4 for tf in positives)
        high_tf_neg = any(tf in negatives and tf_weights[tf] >= 4 for tf in negatives)
        if high_tf_pos and not high_tf_neg:
            parts.append("Higher TFs bullish, outweighing short-term weakness")
        elif high_tf_neg and not high_tf_pos:
            parts.append("Higher TFs bearish, outweighing short-term strength")
        else:
            parts.append(f"Mixed {mode} signals — no dominant side")
    else:
        parts.append("No clear directional bias")

    # Merge neutrals and opposition into one clause
    opposition_clause = []
    if neutrals:
        opposition_clause.append(f"Neutral: {', '.join(neutrals)}")

    if positives and negatives:
        # Determine minority side
        if len(positives) < len(negatives):
            minority = positives
            minority_label = "Opposing bullish"
        elif len(negatives) < len(positives):
            minority = negatives
            minority_label = "Opposing bearish"
        else:
            minority = positives + negatives
            minority_label = "Opposing mix"

        # Sort minority so high-weight TFs come first
        minority_sorted = sorted(minority, key=lambda tf: tf_weights[tf], reverse=True)
        high_weight_opp = [tf for tf in minority_sorted if tf_weights[tf] >= 4]

        if high_weight_opp:
            opposition_clause.append(f"{minority_label} (includes higher TFs: {', '.join(high_weight_opp)})")
        else:
            opposition_clause.append(f"{minority_label}: {', '.join(minority_sorted)}")

    if opposition_clause:
        parts.append(" — ".join(opposition_clause))

    # Add reason tag for decision
    if decision == "Stand Aside":
        parts.append("Conviction too low")
    elif decision in ("Go Long", "Go Short") and confidence_pct < 50:
        parts.append("Low confidence entry")
    elif decision in ("Go Long", "Go Short") and confidence_pct >= 75:
        parts.append("High conviction entry")

    return " — ".join(parts)


def compute_signal_health(bias_conf: float, momentum_conf: float, align_conf: float) -> dict:
    avg_conf = round((bias_conf + momentum_conf + align_conf) / 3, 1)
    return {
        "score_pct": avg_conf,
        "color": confidence_color(avg_conf),
        "label": (
            "Strong Long Bias" if avg_conf >= 75 else
            "Moderate Bias" if avg_conf >= 50 else
            "Weak Bias" if avg_conf >= 25 else
            "No Clear Bias"
        )
    }
