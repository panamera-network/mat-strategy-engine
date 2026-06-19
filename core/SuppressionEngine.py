
from core.BiasEngine import fetch_bias_snapshots
from core.CandleEngine import CandleEngine
from core.StrengthEngine import StrengthEngine
from core.core_models import BiasSnapshot, StructureSnapshot
from core.helper import mode_to_tf



def detect_suppression(snapshot: StructureSnapshot) -> str | None:
    if not snapshot:
        return "No bias data"

    if snapshot.strength < 4:
        return "Low strength (<4)"
    if snapshot.confidence_drop:
        return "Confidence drop"
    if abs(snapshot.momentum_slope) > 6:
        return "Volatile momentum"
    # Add more rules as needed

    return None




def build_bias_diagnostic(symbol: str, tf: str, candle_engine: CandleEngine, strength_engine: StrengthEngine) -> dict:
    snapshots = fetch_bias_snapshots(symbol, tf, candle_engine, strength_engine)
    suppression_reason = detect_suppression(snapshots)
    status = "Suppressed" if suppression_reason else "Active"

    return {
        "symbol": symbol,
        "tf": tf,
        "status": status,
        "suppression_reason": suppression_reason,
        "avg_strength": round(sum(s.strength for s in snapshots) / len(snapshots), 2) if snapshots else 0.0,
        "biases": [s.bias for s in snapshots] if snapshots else [],
        "strengths": [s.strength for s in snapshots] if snapshots else []
    }

def get_suppression(symbol: str, mode: str, candle_engine: CandleEngine, strength_engine: StrengthEngine) -> list[str]:
    tf = mode_to_tf(mode)
    diagnostic = build_bias_diagnostic(symbol, tf, candle_engine, strength_engine)
    reason = diagnostic.get("suppression_reason")
    return [reason] if reason else []

def get_suppression_reasons(snapshot: BiasSnapshot) -> list[str]:
    reasons = []

    if snapshot.strength_diagnostic.strength < 4:
        reasons.append("Low strength (<4)")

    if abs(snapshot.bias_score) < 0.5:
        reasons.append("Bias fading")

    # Optional: add volatility/conflict if snapshot includes historical context

    return reasons
