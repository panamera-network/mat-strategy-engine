
from collections import defaultdict
from engine.bias_map import compute_bias_strength
from engine.core_models import BiasSnapshot
from engine.strength import is_bias_weak


def summarize_currency_strength(bias_snapshots: list[BiasSnapshot]) -> dict:
    currency_map = defaultdict(list)

    for snap in bias_snapshots:
        base, quote = snap.symbol[:3], snap.symbol[3:]
        currency_map[base].append(snap.bias)
        currency_map[quote].append(-snap.bias)  # inverse for quote

    summary = {}
    for currency, biases in currency_map.items():
        avg_bias = sum(biases) / len(biases)
        strength = compute_bias_strength(biases)
        is_weak, reason = is_bias_weak(strength)
        status = "Weak" if is_weak else "Strong" if avg_bias > 0 else "Neutral"

        summary[currency] = {
            "bias": round(avg_bias, 2),
            "strength": round(strength, 2),
            "status": status,
            "tooltip": reason if is_weak else f"Consistent bias over {len(biases)} pairs"
        }

    return summary
