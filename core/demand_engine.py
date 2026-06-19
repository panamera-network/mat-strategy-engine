from core.CandleEngine import CandleEngine
from core.log import log_error


class DemandEngine:
    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine

    def get_label(self, symbol: str, tf: str) -> str:
        snapshots = self.candle_engine.get_snapshots(symbol, tf, count=5)
        if not snapshots:
            return "neutral"

        up_count = sum(1 for c in snapshots if c.close > c.open)
        down_count = sum(1 for c in snapshots if c.close < c.open)

        if up_count > down_count:
            return "demand"
        elif down_count > up_count:
            return "supply"
        return "neutral"

    
demand_engine = DemandEngine(CandleEngine)

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

