
from asyncio.log import logger
from typing import Dict, List
from core.CandleEngine import CandleEngine
from core.StrengthEngine import StrengthEngine
from core.core_models import BiasSnapshot, CandleSnapshot, StrengthDiagnostic


class BiasEngine:
    def __init__(self, candle_engine: CandleEngine, strength_engine: StrengthEngine):
        self.candle_engine = candle_engine
        self.strength_engine = strength_engine

    def get_bias(self, symbol: str, tf: str) -> BiasSnapshot:
        candles = self.candle_engine.get_snapshots(symbol, tf)
        bias_label, bias_score = self.evaluate_bias(candles)
        strength = self.strength_engine.compute_strength(candles)

        return BiasSnapshot(
            symbol=symbol,
            timeframe=tf,
            bias_label=bias_label,
            bias_score=bias_score,
            strength_diagnostic=strength
        )

    def get_multi_tf_map(self, symbol: str, timeframes: List[str]) -> Dict[str, BiasSnapshot]:
        return {
            tf: self.get_bias(symbol, tf)
            for tf in timeframes
        }

    
    def evaluate_bias(self, candles: list[CandleSnapshot]) -> tuple[str, float]:
        if not candles:
            return "neutral", 0.0

        up_closes = sum(1 for c in candles if c.close > c.open)
        down_closes = sum(1 for c in candles if c.close < c.open)

        total = len(candles)
        bias_score = round((up_closes - down_closes) / total * 10, 2)

        if bias_score > 1.5:
            bias_label = "uptrend"
        elif bias_score < -1.5:
         bias_label = "downtrend"
        else:
            bias_label = "neutral"

        return bias_label, bias_score


    def get_bias_map(self, symbol: str, timeframes: list[str]) -> dict[str, dict[str, float | str | StrengthDiagnostic]]:
        bias_map = {}

        for tf in timeframes:
            candles = self.candle_engine.get_snapshots(symbol, tf)
            bias_label, bias_score = self.evaluate_bias(candles)
            strength = self.strength_engine.compute_strength(candles)

            bias_map[tf] = {
                "bias_label": bias_label,
                "bias_score": bias_score,
                "strength_diagnostic": strength  # full object retained
            }

        return bias_map


class OverlayEngine:
    def __init__(self, bias_engine: BiasEngine):
        self.bias_engine = bias_engine

    def get_overlay(self, symbols: list[str], timeframes: list[str]) -> dict[str, dict[str, BiasSnapshot]]:
        overlay = {}
        for symbol in symbols:
            bias_map = self.bias_engine.get_bias_map(symbol, timeframes)
            overlay[symbol] = {
                tf: BiasSnapshot(
                    symbol=symbol,
                    timeframe=tf,
                    bias_score=bias_map[tf]["bias_score"],
                    bias_label=bias_map[tf]["bias_label"],
                    strength_diagnostic=bias_map[tf]["strength_diagnostic"]
                )
                for tf in timeframes
            }
        return overlay


def fetch_bias_snapshots(
    symbol: str,
    tf: str,
    candle_engine: CandleEngine,
    strength_engine: StrengthEngine
) -> list[BiasSnapshot]:
    candles = candle_engine.get_snapshots(symbol, tf, count=5)
    if not candles:
        return []

    strength_diag = strength_engine.compute_strength(candles)

    return [
        BiasSnapshot(
            symbol=symbol,
            timeframe=tf,
            bias_score=compute_bias(c),
            bias_label=label_from_score(compute_bias(c)),
            strength_diagnostic=strength_diag
        )
        for c in candles
    ]

def compute_bias(c: CandleSnapshot) -> float:
    body = c.close - c.open
    wick_top = c.high - max(c.close, c.open)
    wick_bottom = min(c.close, c.open) - c.low
    return round(body * 0.6 + (wick_bottom - wick_top) * 0.4, 2)

def compute_bias_strength(bias_seq: list[float]) -> float:
    if not bias_seq:
        return 0.0

    total = len(bias_seq)
    bullish = bias_seq.count(1.0)
    bearish = bias_seq.count(-1.0)

    dominant = max(bullish, bearish)
    strength = (dominant / total) * 10

    return round(strength, 1)

def get_direction_from_bias(bias: float) -> str:
    if bias > 1.5:
        return "uptrend"
    elif bias < -1.5:
        return "downtrend"
    return "neutral"

def derive_direction(bias_map: dict[str, dict]) -> str:
    biases = [v["bias"] for v in bias_map.values()]
    if all(b == "bullish" for b in biases):
        return "uptrend"
    elif all(b == "bearish" for b in biases):
        return "downtrend"
    else:
        return "choppy"
    
def label_from_score(score: float, threshold: float = 1.5) -> str:
    label = "neutral"
    if score > threshold:
        label = "uptrend"
    elif score < -threshold:
        label = "downtrend"
    logger.debug(f"Bias score: {score:.2f} → Label: {label}")
    return label

