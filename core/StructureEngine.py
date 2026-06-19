

from core.MomentumEngine import MomentumEngine
from core.StrengthEngine import StrengthEngine, is_bias_weak
from core.SuppressionEngine import detect_suppression
from core.core_models import PriceSnapshot
from datetime import datetime, timezone
from core.CandleEngine import CandleEngine
from core.core_models import PriceSnapshot, StructureSnapshot
from core.price import fetch_latest_price_snapshot

candle_engine = CandleEngine()
momentum_engine = MomentumEngine(candle_engine)
strength_engine = StrengthEngine()

# ─────────────────────────────────────────────
# 🧠 Zone Detection
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

# ─────────────────────────────────────────────
# 🔍 Structure Classification
def detect_bos_or_choch(s: StructureSnapshot, epsilon: float = 0.0001) -> dict:
    def is_lower(a: float, b: float) -> bool:
        return a < b - epsilon

    def is_higher(a: float, b: float) -> bool:
        return a > b + epsilon

    print(f"{s.symbol} → prev_zone: {s.prev_zone}, current_high: {s.current_high}, prev_high: {s.prev_high}, current_low: {s.current_low}, prev_low: {s.prev_low}")

    # CHOCH: Reversal logic
    if s.prev_zone in ["HH", "HL"] and is_lower(s.current_low, s.prev_low):
        print(f"{s.symbol} CHOCH Bearish triggered")
        return {"type": "CHOCH", "direction": "Bearish", "valid": True}

    elif s.prev_zone in ["LL", "LH"] and is_higher(s.current_high, s.prev_high):
        print(f"{s.symbol} CHOCH Bullish triggered")
        return {"type": "CHOCH", "direction": "Bullish", "valid": True}

    # BOS: Continuation logic
    if s.prev_zone in ["HH", "HL"] and is_higher(s.current_high, s.prev_high):
        print(f"{s.symbol} BOS Bullish triggered")
        return {"type": "BOS", "direction": "Bullish", "valid": True}

    elif s.prev_zone in ["LL", "LH"] and is_lower(s.current_low, s.prev_low):
        print(f"{s.symbol} BOS Bearish triggered")
        return {"type": "BOS", "direction": "Bearish", "valid": True}

    # Neutral fallback
    print(f"{s.symbol} structure neutral — no CHOCH/BOS detected")
    return {"type": "Neutral", "direction": "Sideways", "valid": False}


# ─────────────────────────────────────────────
# 🧪 CHOCH Detection Utility
def detect_choch(symbol: str, tf: str) -> bool:
    price = fetch_latest_price_snapshot(symbol, tf)
    if not price:
        return False

    current_zone = detect_zone(price)
    structure = StructureSnapshot(
        symbol=symbol,
        timeframe=tf,
        current_high=price.high,
        current_low=price.low,
        prev_high=price.prev_high,
        prev_low=price.prev_low,
        current_zone=current_zone,
        prev_zone=price.prev_zone
    )

    result = detect_bos_or_choch(structure)
    return result["type"] == "CHOCH" and result["valid"]
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

# ─────────────────────────────────────────────
# 🧪 SND SNR Detection Utility
def detect_snd_snr(prev, curr) -> dict:
    range_prev = prev.high - prev.low
    range_curr = curr.high - curr.low

    # SND detection: strong move from tight base
    if range_prev < range_curr * 0.5:
        if curr.close > curr.open and curr.low > prev.low:
            return {"type": "demand", "level": prev.low}
        elif curr.close < curr.open and curr.high < prev.high:
            return {"type": "supply", "level": prev.high}

    # SNR detection: repeated rejection
    if abs(curr.high - prev.high) < 0.0002:
        return {"type": "resistance", "level": curr.high}
    elif abs(curr.low - prev.low) < 0.0002:
        return {"type": "support", "level": curr.low}

    return {"type": "neutral", "level": None}

# ─────────────────────────────────────────────
# 🧪 Fetch prev zone
def fetch_prev_zone(symbol: str, tf: str, candle_engine: CandleEngine) -> str:
    candles = candle_engine.get_snapshots(symbol, tf, count=3)
    if len(candles) < 3:
        return "Neutral"

    prev_price = PriceSnapshot(
        symbol=symbol,
        timeframe=tf,
        high=candles[-2].high,
        low=candles[-2].low,
        prev_high=candles[-3].high,
        prev_low=candles[-3].low
    )

    return detect_zone(prev_price)

# ─────────────────────────────────────────────
# 🧱 Snapshot Builder
def build_snapshot(symbol: str, tf: str, candle_engine: CandleEngine) -> StructureSnapshot | None:
    candles = candle_engine.get_snapshots(symbol, tf, count=6)
    if len(candles) < 2:
        return None

    prev, curr = candles[-2], candles[-1]
    price = PriceSnapshot(
        symbol=symbol,
        timeframe=tf,
        high=curr.high,
        low=curr.low,
        prev_high=prev.high,
        prev_low=prev.low
    )

    current_zone = detect_zone(price)
    snd_snr = detect_snd_snr(prev, curr)
    momentum_snapshot = momentum_engine.compute(candles, symbol, tf)

    structure = StructureSnapshot(
        symbol=symbol,
        timeframe=tf,
        current_high=price.high,
        current_low=price.low,
        prev_high=price.prev_high,
        prev_low=price.prev_low,
        current_zone=current_zone,
        prev_zone=fetch_prev_zone(symbol, tf, candle_engine),
        structure_type="Neutral",
        structure_direction="Sideways",
        structure_valid=False,
        momentum=momentum_snapshot.momentum,
        confidence_drop=momentum_snapshot.confidence_drop,
        timestamp=datetime.now(timezone.utc),
        context_zone=snd_snr["type"],
        context_level=snd_snr["level"]
    )

    structure_type = detect_bos_or_choch(structure)
    structure.structure_type = structure_type["type"]
    structure.structure_direction = structure_type["direction"]
    structure.structure_valid = structure_type["valid"]
    

    structure_map = {
        "BOS": "breakout",
        "CHOCH": "reversal",
        "STACKED": "trend"
    }
    structure.structure = structure_map.get(structure.structure_type, "neutral")

    return structure


# ─────────────────────────────────────────────
# 🧠 Structure Engine Wrapper
class StructureEngine:
    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine

    def get_snapshot(self, symbol: str, tf: str) -> StructureSnapshot | None:
        candles = self.candle_engine.get_snapshots(self, symbol=symbol, tf=tf, count=6)
        if len(candles) < 3:
            return None

        prev, curr = candles[-2], candles[-1]
        price = PriceSnapshot(
            symbol=symbol,
            timeframe=tf,
            high=curr.high,
            low=curr.low,
            prev_high=prev.high,
            prev_low=prev.low
        )

        snd_snr = detect_snd_snr(prev, curr)
        prev_zone = detect_zone(price)
        current_zone = detect_zone(price)
        momentum_snapshot = momentum_engine.compute(candles, symbol, tf)

        snapshot = StructureSnapshot(
            symbol=symbol,
            timeframe=tf,
            current_high=price.high,
            current_low=price.low,
            prev_high=price.prev_high,
            prev_low=price.prev_low,
            current_zone=current_zone,
            prev_zone=prev_zone,
            momentum=momentum_snapshot.momentum,
            confidence_drop=momentum_snapshot.confidence_drop,
            timestamp=datetime.now(timezone.utc),
            context_zone=snd_snr["type"],
            context_level=snd_snr["level"]
        )

        structure_type = detect_bos_or_choch(snapshot)
        snapshot.structure_type = structure_type["type"]
        snapshot.structure_direction = structure_type["direction"]
        snapshot.structure_valid = structure_type["valid"] 
        strength_diag = strength_engine.compute_strength(candles)
        snapshot.strength = strength_diag.strength
        snapshot.body_ratio = strength_diag.avg_body_ratio
        snapshot.momentum_slope = strength_diag.momentum_slope

        # 🔍 Suppression logic — place it right here
        suppression_reason = detect_suppression(snapshot)  # now accepts a single snapshot
        snapshot.suppression_reason = suppression_reason or ""
        snapshot.suppression = suppression_reason is not None


        structure_map = {
            "BOS": "breakout",
            "CHOCH": "reversal",
            "STACKED": "trend"
        }
        snapshot.structure = structure_map.get(snapshot.structure_type, "neutral")

        return snapshot


    def batch_snapshots(self, symbols: list[str], tf: str) -> list[StructureSnapshot]:
        results = []
        for symbol in symbols:
            snapshot = self.get_snapshot(symbol, tf)
            if snapshot and snapshot.structure_valid:
                results.append(snapshot)
        return results

