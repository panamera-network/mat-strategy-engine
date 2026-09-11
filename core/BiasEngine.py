
import logging
from typing import Dict, List, Optional
from core.CandleEngine import CandleEngine
from core.StrengthEngine import StrengthEngine
from core.core_models import BiasSnapshot, CandleSnapshot, StrengthDiagnostic, StructureSnapshot

logger = logging.getLogger(__name__)

STRUCTURE_BIAS_SCORE = {"BOS": 8.0, "CHOCH": 10.0}  # CHoCH = trend flip, stronger signal


class BiasEngine:
    def __init__(self, candle_engine: CandleEngine, strength_engine: StrengthEngine, structure_engine=None):
        self.candle_engine = candle_engine
        self.strength_engine = strength_engine
        # Optional — injected by the composition root (api/core_router.py).
        # Not imported at module level (would recreate the circular import
        # structure_utils.py was split out to avoid: StructureEngine ->
        # SuppressionEngine -> BiasEngine). When a caller doesn't hand in an
        # explicit structure_snapshot/structure_map (get_bias/get_bias_map
        # below), this is used to resolve one anyway — so every caller ends
        # up on StructureEngine.get_snapshot()'s result, never a homegrown
        # detection, whether or not it bothers to pass one in explicitly.
        self.structure_engine = structure_engine

    def _resolve_structure(self, symbol: str, tf: str, structure_snapshot: Optional[StructureSnapshot], cache=None) -> Optional[StructureSnapshot]:
        if structure_snapshot is not None:
            return structure_snapshot
        if self.structure_engine is not None:
            return self.structure_engine.get_snapshot(symbol, tf, cache=cache)
        return None

    def get_bias(self, symbol: str, tf: str, structure_snapshot: Optional[StructureSnapshot] = None, cache=None) -> BiasSnapshot:
        candles = self.candle_engine.get_snapshots(symbol, tf, cache=cache)
        structure_snapshot = self._resolve_structure(symbol, tf, structure_snapshot, cache=cache)
        bias_label, bias_score = self.evaluate_bias(candles, structure_snapshot=structure_snapshot)
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


    def evaluate_bias(self, candles: list[CandleSnapshot], structure_snapshot: Optional[StructureSnapshot] = None) -> tuple[str, float]:
        if not candles:
            return "neutral", 0.0

        # BOS/CHoCH is StructureEngine's sole responsibility now — consume its
        # result instead of detecting structure independently here. (Previously
        # this ran find_swings()/detect_structure_event() on whatever candle
        # window get_snapshots() returned by default, which is a different
        # window than StructureEngine's own SWING_LOOKBACK slice — the two
        # engines could disagree on BOS/CHoCH for the same symbol/tf.)
        if (
            structure_snapshot is not None
            and structure_snapshot.structure_valid
            and structure_snapshot.structure_type in STRUCTURE_BIAS_SCORE
        ):
            direction = structure_snapshot.structure_direction
            score = STRUCTURE_BIAS_SCORE[structure_snapshot.structure_type]
            bias_score = score if direction == "Bullish" else -score
            bias_label = "uptrend" if direction == "Bullish" else "downtrend"
            return bias_label, bias_score

        # Fallback: no confirmed BOS/CHoCH (or no structure snapshot supplied)
        # — use the existing candle-ratio logic.
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


    def get_bias_map(self, symbol: str, timeframes: list[str], structure_map: Optional[dict[str, StructureSnapshot]] = None, cache=None) -> dict[str, dict[str, float | str | StrengthDiagnostic]]:
        bias_map = {}

        for tf in timeframes:
            candles = self.candle_engine.get_snapshots(symbol, tf, cache=cache)
            structure_snapshot = structure_map.get(tf) if structure_map else None
            structure_snapshot = self._resolve_structure(symbol, tf, structure_snapshot, cache=cache)
            bias_label, bias_score = self.evaluate_bias(candles, structure_snapshot=structure_snapshot)
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

