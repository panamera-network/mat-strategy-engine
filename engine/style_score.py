from engine.core_models import DiagnosticSnapshot


def compute_style_score(snapshot: DiagnosticSnapshot) -> tuple[float, dict]:
    breakdown = {}
    score = 0

    # Zone expectations
    expected = {
        "LL": {
            "structure_signal": "BOS",
            "divergence": "Bearish Divergence",
            "direction": "Bearish",
            "momentum_sign": -1
        },
        "HH": {
            "structure_signal": "CHOCH",
            "divergence": "Bullish Divergence",
            "direction": "Bullish",
            "momentum_sign": 1
        }
    }

    zone = snapshot.zone
    zone_expect = expected.get(zone, {})

    # Structure signal match
    if snapshot.structure_signal == zone_expect.get("structure_signal"):
        breakdown["structure_signal"] = 2
        score += 2
    else:
        breakdown["structure_signal"] = 0

    # Divergence match
    if snapshot.divergence == zone_expect.get("divergence"):
        breakdown["divergence"] = 2
        score += 2
    else:
        breakdown["divergence"] = 0

    # Direction match
    if snapshot.direction == zone_expect.get("direction"):
        breakdown["direction"] = 2
        score += 2
    else:
        breakdown["direction"] = 0

    # Momentum sign match
    if zone_expect.get("momentum_sign") is not None:
        if snapshot.momentum * zone_expect["momentum_sign"] > 0:
            breakdown["momentum"] = 2
            score += 2
        else:
            breakdown["momentum"] = 0
    else:
        breakdown["momentum"] = 0

    final_score = round(score / 8, 2)
    return final_score, breakdown