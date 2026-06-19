from engine.core_models import CandleSnapshot, MomentumPoint, MomentumSnapshot
from engine.log import log_error
from mt5.fetcher import fetch_candles



class MomentumEngine:
    def get_score(self, symbol: str, tf: str) -> float:
        points = fetch_momentum_points(symbol, tf)
        if len(points) < 2:
            return 0.0

        p1, p2 = points[-2], points[-1]
        if p2.price > p1.price and p2.momentum < p1.momentum:
            return -1.0  # bearish divergence
        elif p2.price < p1.price and p2.momentum > p1.momentum:
            return 1.0   # bullish divergence
        return 0.0      # no divergence
    
momentum_engine = MomentumEngine()
    
def fetch_momentum_score(symbol: str, tf: str) -> float:
    try:
        score = momentum_engine.get_score(symbol, tf)
        return round(score, 2)
    except Exception as e:
        log_error(symbol, tf, "momentum_fetch", str(e))
        return 0.0
    
def get_momentum(symbol: str, mode: str) -> float:
    tf = "M5" if mode == "scalping" else "H1"
    return fetch_momentum_score(symbol, tf)

def get_color(self) -> str:
    if self.confidence_drop:
        return "#FF0000"
    elif self.momentum > 5:
        return "#00FF00"
    elif self.momentum < -5:
        return "#0000FF"
    return "#CCCCCC"

def compute_momentum_strength(candle: CandleSnapshot) -> float:
    body = abs(candle.close - candle.open)
    wick = (candle.high - candle.low) - body
    total = body + wick

    if total == 0:
        return 0.0

    strength = (body / total) * 10  # scale to 0–10
    return round(strength, 1)

def detect_momentum_divergence(points: list[MomentumPoint]) -> str:
    if len(points) < 2:
        return "None"

    p1, p2 = points[-2], points[-1]

    if p2.price > p1.price and p2.momentum < p1.momentum:
        return "Bearish Divergence"
    elif p2.price < p1.price and p2.momentum > p1.momentum:
        return "Bullish Divergence"

    return "None"

def fetch_momentum_points(symbol: str, tf: str) -> list[MomentumPoint]:
    candles = fetch_candles(symbol, tf)
    if not candles or len(candles) < 10:
        log_error(symbol, tf, "momentum fetch", "insufficient candles")
        return []


    return [
        MomentumPoint(symbol, tf, price=c.close, momentum=c.close - c.open)
        for c in candles[-10:]
    ]

def detect_divergence(symbol: str, tf: str, direction: str) -> bool:
    points = fetch_momentum_points(symbol, tf)  # ← your actual fetch
    result = detect_momentum_divergence(points)
    return result == f"{direction.capitalize()} Divergence"

def analyze_momentum(points: list[float]) -> MomentumSnapshot:
    if not points:
        return MomentumSnapshot(
            symbol="",
            timeframe="",
            momentum=0.0,
            score=0.0,
            divergence="None",
            confidence_drop=True,
            direction="Neutral"
        )

    latest = points[-1]
    divergence = detect_momentum_divergence(points)
    confidence_drop = divergence != "None" and latest < 4

    direction = (
        "Bullish" if latest > 5
        else "Bearish" if latest < -5
        else "Neutral"
    )

    return MomentumSnapshot(
        symbol="",         # Fill this upstream if needed
        timeframe="",      # Fill this upstream if needed
        momentum=latest,
        score=latest,
        divergence=divergence,
        confidence_drop=confidence_drop,
        direction=direction
    )


