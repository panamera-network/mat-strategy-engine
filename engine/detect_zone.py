from engine.core_models import PriceSnapshot, StructureSnapshot
from engine.log import log_error
from engine.price import fetch_latest_price_snapshot



def get_structure_snapshot(symbol: str, tf: str) -> StructureSnapshot | None:
    pivots = fetch_pivots(symbol, tf)
    if not pivots or any(pivots.get(k) is None for k in ["current_high", "current_low", "prev_high", "prev_low"]):
        log_error(symbol, tf, "structure snapshot", "missing pivot data")
        return None

    ch, cl, ph, pl = pivots["current_high"], pivots["current_low"], pivots["prev_high"], pivots["prev_low"]

    # Structural logic (optional: embed label/direction)
    return StructureSnapshot(
        symbol=symbol,
        timeframe=tf,
        current_high=ch,
        current_low=cl,
        prev_high=ph,
        prev_low=pl,
        prev_zone=pivots.get("prev_zone", None),
    )




def fetch_pivots(symbol: str, tf: str) -> dict:
    from engine.engine_core import build_snapshot
    snapshot = build_snapshot(symbol, tf)
    structure = snapshot.structure  # StructureSnapshot

    return {
        "current_high": structure.current_high,
        "current_low": structure.current_low,
        "prev_high": structure.prev_high,
        "prev_low": structure.prev_low,
        "prev_zone": structure.prev_zone
    }

def detect_zone(price: PriceSnapshot) -> str:
    if price.high > price.prev_high and price.low > price.prev_low:
        return "HH"
    elif price.high > price.prev_high and price.low < price.prev_low:
        return "HL"
    elif price.high < price.prev_high and price.low > price.prev_low:
        return "LH"
    elif price.high < price.prev_high and price.low < price.prev_low:
        return "LL"
    return "Neutral"

def detect_bos_or_choch(s: StructureSnapshot) -> str:
    # CHOCH: Bullish → Bearish or Bearish → Bullish
    if s.prev_zone in ["HH", "HL"] and s.current_low < s.prev_low:
        return "CHOCH"
    elif s.prev_zone in ["LL", "LH"] and s.current_high > s.prev_high:
        return "CHOCH"
    
    # BOS: Continuation in trend direction
    if s.prev_zone in ["HH", "HL"] and s.current_high > s.prev_high:
        return "BOS"
    elif s.prev_zone in ["LL", "LH"] and s.current_low < s.prev_low:
        return "BOS"
    
    return "Neutral"

def detect_choch(symbol: str, tf: str) -> bool:
    price = fetch_latest_price_snapshot(symbol, tf)  # ← your actual fetch
    zone = detect_zone(price)

    structure = StructureSnapshot(
        prev_zone=zone,
        current_high=price.high,
        current_low=price.low,
        prev_high=price.prev_high,
        prev_low=price.prev_low,
    )

    return detect_bos_or_choch(structure) == "CHOCH"