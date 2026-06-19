

from bias_map import get_bias_map
from engine import detect_shift
from engine.bias_map import detect_trend
from engine.core_models import BiasSnapshot
from engine.demand import get_demand

from engine.momentum_engine import get_momentum



def group_by_mode(snapshots: list[BiasSnapshot]) -> dict:
    scalping_tf = {"M1", "M5", "M15", "M30"}
    swing_tf = {"H1", "H4", "D1", "W1"}

    grouped = {"scalp": [], "swing": []}

    for snap in snapshots:
        if snap.timeframe in scalping_tf:
            grouped["scalp"].append(snap)
        elif snap.timeframe in swing_tf:
            grouped["swing"].append(snap)

    return grouped

def summarize_mode(snapshots: list[BiasSnapshot]) -> dict:
    if not snapshots:
        return {"bias": 0, "strength": 0, "status": "Suppressed", "trend": "Unclear"}

    avg_bias = sum(s.bias for s in snapshots) / len(snapshots)
    avg_strength = sum(s.strength for s in snapshots) / len(snapshots)

    status = "Strong" if avg_bias >= 7 else "Weak" if avg_bias <= -7 else "Neutral"
    if avg_strength < 4:
        status = "Suppressed"

    trend = detect_trend(avg_bias, avg_strength)

    return {
        "bias": round(avg_bias, 1),
        "strength": round(avg_strength, 1),
        "status": status,
        "trend": trend
    }





def get_style_score(symbol: str, mode: str) -> tuple[float, dict]:
    shift = detect_shift(symbol, mode)
    momentum = get_momentum(symbol, mode)
    demand = get_demand(symbol, mode)
    bias_tf = "M5" if mode == "scalping" else "H1"
    bias = get_bias_map(symbol).get(bias_tf, {})

    components = {}

    score = (momentum - 50) / 5
    components["momentum"] = round(score, 2)

    if bias.get("bias") == "bullish":
        score += 2
        components["bias_alignment"] = +2
    elif bias.get("bias") == "bearish":
        score -= 2
        components["bias_alignment"] = -2
    else:
        components["bias_alignment"] = 0

    demand_map = {
        "strong buy": +2,
        "buy": +1,
        "neutral": 0,
        "sell": -1,
        "strong sell": -2
    }
    demand_score = demand_map.get(demand.lower(), 0)
    score += demand_score
    components["demand"] = demand_score

    if not shift.get("confirmed"):
        score *= 0.5
        components["confirmation_penalty"] = True
    else:
        components["confirmation_penalty"] = False

    return round(score, 2), components
