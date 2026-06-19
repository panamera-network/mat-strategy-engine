from engine.core_models import DiagnosticSnapshot


def compute_confidence(snapshot: DiagnosticSnapshot) -> tuple[float, dict]:
    breakdown = {}
    score = 0

    # Structure signal
    if snapshot.structure_signal == "CHOCH":
        breakdown["structure_signal"] = 3
        score += 3
    elif snapshot.structure_signal == "BOS":
        breakdown["structure_signal"] = 2
        score += 2
    else:
        breakdown["structure_signal"] = 0

    # Divergence
    if snapshot.divergence in ["Bullish Divergence", "Bearish Divergence"]:
        breakdown["divergence"] = 2
        score += 2
    else:
        breakdown["divergence"] = 0

    # Direction
    if snapshot.direction != "Neutral":
        breakdown["direction"] = 2
        score += 2
    else:
        breakdown["direction"] = 0

    # Confidence drop
    if not snapshot.confidence_drop:
        breakdown["confidence_drop"] = 1
        score += 1
    else:
        breakdown["confidence_drop"] = 0

    final_score = round(score / 10, 2)
    return final_score, breakdown