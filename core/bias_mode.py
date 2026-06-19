#bias_mode.py
from core.TrendEngine import detect_trend
from core.core_models import BiasSnapshot


def group_by_mode(snapshots: list[BiasSnapshot]) -> dict[str, list[BiasSnapshot]]:
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
        return {
            "bias": 0,
            "strength": 0,
            "status": "Suppressed",
            "trend": "Unclear",
            "trend_reason": "No data",
            "confidence": 0,
            "suppressed_count": 0,
            "alignment": False
        }

    avg_bias = sum(s.bias for s in snapshots) / len(snapshots)
    avg_strength = sum(s.strength for s in snapshots) / len(snapshots)

    # Status logic
    status = "Strong" if avg_bias >= 7 else "Weak" if avg_bias <= -7 else "Neutral"
    if avg_strength < 4:
        status = "Suppressed"

    # Trend logic
    trend_info = detect_trend(avg_bias, avg_strength)
    trend = trend_info["trend"]
    reason = trend_info["reason"]

    # Confidence score
    biases = [s.bias for s in snapshots]
    aligned = all_same_direction(biases)
    confidence = int(avg_strength * 10)
    if not aligned:
        confidence = int(confidence * 0.6)

    suppressed_count = sum(1 for s in snapshots if s.strength < 2)

    return {
        "bias": round(avg_bias, 1),
        "strength": round(avg_strength, 1),
        "status": status,
        "trend": trend,
        "trend_reason": reason,
        "confidence": confidence,
        "suppressed_count": suppressed_count,
        "alignment": aligned
    }


def all_same_direction(biases: list[float]) -> bool:
    directions = [get_direction(b) for b in biases if b != 0]
    return len(set(directions)) == 1 and directions != []

def get_direction(bias: float) -> str:
    if bias > 0:
        return "bullish"
    elif bias < 0:
        return "bearish"
    else:
        return "neutral"


def hydrate_symbol_payload(symbol: str, snapshots: list[BiasSnapshot]) -> dict:
    grouped = group_by_mode(snapshots)

    bias_map = {
        s.timeframe: {
            "bias": s.bias,
            "strength": s.strength,
            "status": "Suppressed" if s.strength < 2 else "Active",
            "direction": get_direction(s.bias)
        }
        for s in snapshots
    }

    return {
        symbol: {
            "bias": bias_map,
            "scalping": summarize_mode(grouped["scalp"]),
            "swing": summarize_mode(grouped["swing"]),
            "timeframes_used": [s.timeframe for s in snapshots],
        }
    }


def hydrate_all_symbols(data: dict[str, list[BiasSnapshot]]) -> dict[str, dict]:
    return {
        symbol: hydrate_symbol_payload(symbol, snapshots)[symbol]
        for symbol, snapshots in data.items()
    }

def get_mode(tf: str) -> str:
    if tf in {"M1", "M5", "M15", "M30"}:
        return "scalp"
    elif tf in {"H1", "H4", "D1", "W1"}:
        return "swing"
    return "unknown"
