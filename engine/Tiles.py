
from engine.bias_shift import check_trigger
from engine.core_models import BiasSnapshot, DiagnosticTile, MomentumSnapshot
from engine.demand import fetch_demand_label

from engine.engine_core import compute_signal_duration, confirm_shift, fetch_bias
from engine.momentum_engine import fetch_momentum_score



def build_tile(
    bias_snap: BiasSnapshot,
    zone: str,
    structure_event: str,
    momentum_snap: MomentumSnapshot
) -> DiagnosticTile:
    status = "Strong" if abs(bias_snap.bias) >= 7 and bias_snap.strength >= 7 else "Weak"
    if bias_snap.strength < 4 or momentum_snap.confidence_drop:
        status = "Suppressed"

    return DiagnosticTile(
        symbol=bias_snap.symbol,
        timeframe=bias_snap.timeframe,
        bias=bias_snap.bias,
        strength=bias_snap.strength,
        zone=zone,
        structure_event=structure_event,
        momentum=momentum_snap.momentum,
        divergence=momentum_snap.divergence,
        confidence_drop=momentum_snap.confidence_drop,
        status=status
    )

def build_overlay_tile(symbol: str, tf: str) -> dict:
    bias, strength = fetch_bias(symbol, tf)
    momentum = fetch_momentum_score(symbol, tf)
    demand = fetch_demand_label(symbol, tf)
    duration = compute_signal_duration(symbol, tf)
    trigger = check_trigger(symbol, tf)
    confirmed = confirm_shift(symbol, tf)

    return {
        "symbol": symbol,
        "timeframe": tf,
        "bias": bias,
        "strength": strength,
        "momentum": momentum,
        "demand": demand,
        "duration": duration,
        "trigger": trigger,
        "confirmed": confirmed
    }