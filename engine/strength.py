
from engine.core_models import DiagnosticSnapshot

def compute_bias_strength(bias_seq: list[float]) -> float:
    if not bias_seq:
        return 0.0

    total = len(bias_seq)
    bullish = bias_seq.count(1.0)
    bearish = bias_seq.count(-1.0)

    dominant = max(bullish, bearish)
    strength = (dominant / total) * 10

    return round(strength, 1)

def is_bias_weak(strength: float, threshold: float = 4.0) -> tuple[bool, str]:
    if strength < threshold:
        return True, f"Bias strength {strength} is below threshold {threshold}"
    return False, ""

def get_suppression_reasons(snapshot: DiagnosticSnapshot) -> list[str]:
    reasons = []

    if snapshot.momentum < 3:
        reasons.append("Low momentum")

    if snapshot.confidence_drop:
        reasons.append("Confidence drop")

    if snapshot.divergence == "None" and snapshot.structure_signal == "CHOCH":
        reasons.append("CHOCH without divergence")

    # Add more rules as needed
    return reasons

