from engine.bias_mode import get_style_score

from engine.core_models import DiagnosticSnapshot, DiagnosticValidation
from engine.demand import get_demand

from engine.engine_core import build_snapshot, detect_shift, get_bias_map, get_duration
from engine.momentum_engine import get_momentum
from engine.strength import get_suppression_reasons



def validate_diagnostic(snapshot: DiagnosticSnapshot) -> DiagnosticValidation:
    # Alignment logic
    bullish_struct = snapshot.structure_signal == "BOS" and snapshot.direction == "Bullish"
    bearish_struct = snapshot.structure_signal == "BOS" and snapshot.direction == "Bearish"
    reversal_struct = snapshot.structure_signal == "CHOCH"

    # Confidence logic
    weak_momentum = snapshot.momentum < 4 or snapshot.confidence_drop

    # Color logic
    if reversal_struct and snapshot.divergence != "None":
        color = "orange"
        valid = not weak_momentum
        tooltip = f"{snapshot.structure_signal} + {snapshot.divergence} → Reversal setup"
    elif bullish_struct and not weak_momentum:
        color = "green"
        valid = True
        tooltip = f"BOS + strong bullish momentum → Continuation"
    elif bearish_struct and not weak_momentum:
        color = "red"
        valid = True
        tooltip = f"BOS + strong bearish momentum → Continuation"
    else:
        color = "gray"
        valid = False
        tooltip = f"{snapshot.structure_signal} with weak or conflicting momentum"

    return DiagnosticValidation(
        is_valid=valid,
        tile_color=color,
        tooltip=tooltip
    )

def build_symbol_diagnostics(symbol: str) -> dict:
    bias_map = get_bias_map(symbol)  # returns { "M1": {...}, "M5": {...}, ... }
    scalping_shift = detect_shift(symbol, mode="scalping")
    swing_shift = detect_shift(symbol, mode="swing")
    scalping_momentum = get_momentum(symbol, mode="scalping")
    swing_momentum = get_momentum(symbol, mode="swing")
    scalping_demand = get_demand(symbol, mode="scalping")
    swing_demand = get_demand(symbol, mode="swing")
    scalping_duration = get_duration(symbol, mode="scalping")
    swing_duration = get_duration(symbol, mode="swing")
    scalping_snapshot = build_snapshot(symbol, "M5")
    swing_snapshot = build_snapshot(symbol, "H1")
    scalp_score, scalp_breakdown = get_style_score(symbol, "scalping")
    swing_score, swing_breakdown = get_style_score(symbol, "swing")

    return {
        symbol: {
            "bias": bias_map,
            "scalping": {
                "shift": scalping_shift,
                "suppression": get_suppression_reasons(scalping_snapshot),
                "momentum": scalping_momentum,
                "demand": scalping_demand,
                "duration": scalping_duration,
                "style_score": scalp_score,
                "style_breakdown": scalp_breakdown
            },
            "swing": {
                "shift": swing_shift,
                "suppression": get_suppression_reasons(swing_snapshot),
                "momentum": swing_momentum,
                "demand": swing_demand,
                "duration": swing_duration,
                "style_score": swing_score,
                "style_breakdown": swing_breakdown
            }
        }
    }