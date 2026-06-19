
from typing import Dict, List, Optional


from engine.confidence import compute_confidence
from engine.demand import fetch_demand_label, get_demand
from engine.bias_map import compute_bias_sequence, compute_bias_strength, derive_direction
from engine.core_models import BiasShiftEvent, CandleSnapshot, DiagnosticSnapshot, PriceSnapshot, StrategySnapshot, StructureSnapshot

from engine.detect_zone import detect_zone, get_structure_snapshot
from engine.helper import get_utc_now, mode_to_tf
from engine.log import log_error, log_suppression

from engine.momentum_engine import MomentumEngine, detect_divergence, fetch_momentum_score, get_momentum
from engine.price import fetch_latest_price_snapshot
from engine.snapshot_builder import build_diagnostic_snapshot
from engine.strength import  get_suppression_reasons, is_bias_weak
from engine.style_score import compute_style_score
from mt5.fetcher import fetch_candles


class CandleSource:
    def fetch(self, symbol: str, tf: str) -> list[CandleSnapshot]:
        try:
            raw = fetch_candles(symbol, tf)  # Replace with actual fetch
            return [
                CandleSnapshot(**(c.model_dump() if hasattr(c, "dict") else c))
                for c in raw
            ]
        except Exception as e:
            log_error(symbol, tf, "candle_fetch", str(e))
            return []

class BiasEngine:
    def __init__(self, candle_source: CandleSource):
        self.candle_source = candle_source

    def get(self, symbol: str, tf: str) -> dict:
        candles = self.candle_source.fetch(symbol, tf)
        bias_seq = compute_bias_sequence(candles)
        scaled_bias = round(bias_seq[-1] * 10, 1) if bias_seq else 0.0
        strength = compute_bias_strength(bias_seq)

        suppressed, reason = is_bias_weak(strength)
        return {
            "bias": scaled_bias if not suppressed else "neutral",
            "strength": strength if not suppressed else 0.0,
            "suppressed": suppressed,
            "reason": reason if suppressed else ""
        }



class StructureEngine:
    @staticmethod
    def get_snapshot(symbol: str, tf: str) -> StructureSnapshot:
        price = fetch_latest_price_snapshot(symbol, tf)
        zone = detect_zone(price)

        return StructureSnapshot(
            symbol=symbol,
            timeframe=tf,
            prev_zone=zone,
            current_high=price.high,
            current_low=price.low,
            prev_high=price.prev_high,
            prev_low=price.prev_low
        )

class ZoneEngine:
    def confirm_shift_zone(self, symbol: str, tf: str) -> bool:
        price = fetch_latest_price_snapshot(symbol, tf)
        zone = detect_zone(price)
        return zone in ["HH", "LL"]  # or whatever your shift criteria is



class CandleEngine:
    def confirm_structure(self, symbol: str, tf: str) -> bool:
        price = fetch_latest_price_snapshot(symbol, tf)
        structure = StructureSnapshot(
            prev_zone=detect_zone(price),
            current_high=price.high,
            current_low=price.low,
            prev_high=price.prev_high,
            prev_low=price.prev_low,
        )
        return detect_zone.detect_bos_or_choch(structure) in ["CHOCH", "BOS"]

class BiasShiftTracker:
    def __init__(self):
        self.bias_map: Dict[str, str] = {}  # symbol → bias
        self.shift_log: List[BiasShiftEvent] = []

    def update(self, snapshot: DiagnosticSnapshot):
        key = f"{snapshot.symbol}_{snapshot.timeframe}"
        prev_bias = self.bias_map.get(key, "Neutral")
        event = detect_bias_shift(prev_bias, snapshot)

        if event:
            self.shift_log.append(event)
            if event.confirmed:
                self.bias_map[key] = event.new_bias

        return event
    
class SignalTracker:
    def get_duration(self, symbol: str, tf: str) -> int:
        candles = fetch_candles(symbol, tf)
        count = 0
        for c in reversed(candles):
            if c.close > c.open:
                count += 1
            else:
                break
        return count

candle_source = CandleSource()
bias_engine = BiasEngine(candle_source)



def fetch_bias(symbol: str, tf: str) -> tuple[str, float]:
    try:
        bias_data = bias_engine.get(symbol, tf)  # your internal source
        bias = bias_data.get("bias", "neutral")
        strength = bias_data.get("strength", 0.0)

        # Suppression logic
        if bias_data.get("suppressed"):
            log_suppression(symbol, tf, reason="Bias suppressed due to conflicting signals")
            bias = "neutral"
            strength = 0.0

        return bias, strength

    except Exception as e:
        log_error(symbol, tf, "bias_fetch", str(e))
        return "neutral", 0.0

structure_engine = StructureEngine()
momentum_engine = MomentumEngine()
zone_engine = ZoneEngine()
candle_engine = CandleEngine()
signal_tracker = SignalTracker()


def build_snapshot(symbol: str, tf: str) -> DiagnosticSnapshot:
    snapshot = build_core_snapshot(symbol, tf)
    snapshot.demand_label = fetch_demand_label(symbol, tf)
    snapshot.signal_duration = compute_signal_duration(symbol, tf)
    snapshot.confidence_score, snapshot.confidence_breakdown = compute_confidence(snapshot)
    snapshot.style_score, snapshot.style_breakdown = compute_style_score(snapshot)
    snapshot.suppression = get_suppression_reasons(snapshot)
    structure = StructureEngine.get_snapshot(symbol, tf)
    snapshot.structure = structure

    return snapshot

def build_core_snapshot(symbol: str, tf: str) -> DiagnosticSnapshot:
    structure = structure_engine.get_snapshot(symbol, tf)
    momentum_points = [momentum_engine.get_score(symbol, tf)]
    return build_diagnostic_snapshot(structure, momentum_points)

def confirm_shift(symbol: str, tf: str) -> bool:
    try:
        zone_match = zone_engine.confirm_shift_zone(symbol, tf)
        candle_confirm = candle_engine.confirm_structure(symbol, tf)
        return zone_match and candle_confirm
    except Exception as e:
        log_error(symbol, tf, "shift_confirm", str(e))
        return False
    
def detect_bias_shift(prev_bias: str, symbol: str, mode: str) -> Optional[BiasShiftEvent]:
    snapshot = build_snapshot(symbol, mode_to_tf(mode))

    is_reversal = snapshot.structure_signal == "CHOCH" and snapshot.divergence != "None"
    if not is_reversal:
        return None

    new_bias = snapshot.direction
    confirmed = snapshot.momentum >= 5 and not snapshot.confidence_drop
    strength = compute_bias_strength(snapshot.bias_sequence)
    weak, reason = is_bias_weak(strength)
    if weak:
        suppression.append(reason)

    # Layered suppression: strategy-level + snapshot-level
    suppression = get_suppression(symbol, mode)
    suppression += get_suppression_reasons(snapshot)

    return BiasShiftEvent(
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        previous_bias=prev_bias,
        new_bias=new_bias,
        trigger=f"CHOCH + {snapshot.divergence}",
        confirmed=confirmed,
        momentum=snapshot.momentum,
        confidence_drop=snapshot.confidence_drop,
        timestamp=get_utc_now(),
        suppression=suppression
    )

def is_confirmed(snapshot: DiagnosticSnapshot) -> bool:
    return snapshot.momentum >= 5 and not snapshot.confidence_drop

def get_duration(symbol: str, mode: str) -> str:
    tf = "M5" if mode == "scalping" else "H1"
    minutes = compute_signal_duration(symbol, tf)
    return f"{minutes} min"

def compute_signal_duration(symbol: str, tf: str) -> int:
    try:
        duration = signal_tracker.get_duration(symbol, tf)
        return int(duration)
    except Exception as e:
        log_error(symbol, tf, "duration_fetch", str(e))
        return 0
    
def format_duration(seconds: int) -> str:
    return f"{seconds // 60} min"

def build_strategy_snapshot(symbol: str, tf: str, bias_map: dict[str, dict]) -> StrategySnapshot:
    direction = derive_direction(bias_map)
    shift = detect_shift(bias_map, tf)  # Assuming this is already defined
    momentum = fetch_momentum_score(symbol, tf)
    demand = fetch_demand_label(symbol, tf)
    duration = f"{compute_signal_duration(symbol, tf)} min"

    return StrategySnapshot(
        direction=direction,
        shift=shift,
        momentum=momentum,
        demand=demand,
        duration=duration
    )

def get_bias_map(symbol: str) -> dict:
	timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
	bias_map = {} 
	for tf in timeframes:
		bias, strength = fetch_bias(symbol, tf) # your internal logic 
		bias_map[tf] = { "bias": bias, "strength": strength }
	return bias_map

def detect_shift(symbol: str, mode: str, price: PriceSnapshot) -> dict:
    tf = "M5" if mode == "scalping" else "H1"
    structure = get_structure_snapshot(symbol, tf)  # Returns StructureSnapshot
    divergence_confirmed = detect_divergence(symbol, tf, structure.direction)
    zone_label = detect_zone(price)

    bias_map = get_bias_map(symbol)
    prev_bias = bias_map.get(tf, {}).get("previous_bias", "Neutral")
    new_bias = bias_map.get(tf, {}).get("bias", "Neutral")

    confirmed = structure.label in ["CHOCH", "BOS"] and divergence_confirmed
    trigger = f"{structure.label} + {structure.direction} divergence" if confirmed else "None"
    reason = (
        f"{tf} confirmed shift from {prev_bias} to {new_bias} at {zone_label}"
        if confirmed else f"{tf} shift not confirmed"
    )

    return {
        "symbol": symbol,
        "timeframe": tf,
        "previous_bias": prev_bias,
        "new_bias": new_bias,
        "confirmed": confirmed,
        "trigger": trigger,
        "reason": reason,
        "structure": structure.label,
        "direction": structure.direction,
        "zone": zone_label
    }

def get_suppression(symbol: str, mode: str) -> list[str]:
    reasons = []

    shift = detect_shift(symbol, mode)
    momentum = get_momentum(symbol, mode)
    demand = get_demand(symbol, mode)
    bias_tf = "M5" if mode == "scalping" else "H1"
    bias = get_bias_map(symbol).get(bias_tf, {})

    if not shift.get("confirmed"):
        reasons.append("Unconfirmed shift")

    if abs(momentum) < 20:
        reasons.append("Low momentum")

    if demand.lower() in ["neutral", "none"]:
        reasons.append("No demand signal")

    if bias.get("bias") == "neutral":
        reasons.append("Neutral bias")

    return reasons