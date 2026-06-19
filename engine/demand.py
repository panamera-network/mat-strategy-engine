
from engine.demand_engine import DemandEngine
from engine.log import log_error

demand_engine = DemandEngine()

def fetch_demand_label(symbol: str, tf: str) -> str:
    try:
        label = demand_engine.get_label(symbol, tf)
        return label or "neutral"
    except Exception as e:
        log_error(symbol, tf, "demand_fetch", str(e))
        return "neutral"

def get_demand(symbol: str, mode: str) -> str:
    tf = "M5" if mode == "scalping" else "H1"
    return fetch_demand_label(symbol, tf)  # e.g. "strong sell", "buy"