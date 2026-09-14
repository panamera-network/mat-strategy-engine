from core.CandleEngine import CandleEngine
from core.core_models import CandleSnapshot, MomentumSnapshot
from core.demand_engine import compute_atr

# Fix #6V — minimum candles for a genuine 14-period ATR (14 true-range
# values need 15 candles). Below this, atr_normalized_momentum is None
# rather than computed from a shorter/different-period ATR.
ATR14_MIN_CANDLES = 15


class MomentumEngine:
    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine  # ✅ This line was missing

    def compute(self, candles: list[CandleSnapshot], symbol: str, timeframe: str) -> MomentumSnapshot:
        if len(candles) < 6:
            return MomentumSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                momentum=0.0,
                slope=0.0,
            )

        closes = [c.close for c in candles[-6:]]
        slope1 = closes[3] - closes[0]
        slope2 = closes[5] - closes[2]
        acceleration = slope2 - slope1
        raw_score = slope2
        scaled_score = max(0.0, min(10.0, abs(raw_score) * 2.5))  # tweak scale_factor

        # Placeholder logic — you can refine this
        threshold = 0.5
        confidence_drop = slope2 < slope1 and abs(acceleration) > threshold

        # Fix #6U/#6V — canonical signed, dimensionless momentum: the same
        # slope2 (3-bar displacement) above, divided by ATR14 — no clamp,
        # no multiplier, no threshold. Uses whatever `candles` this call
        # was already given (StructureEngine's canonical path already
        # passes its full 26-candle FETCH_COUNT window here — no extra
        # fetch). If this call was given fewer than ATR14_MIN_CANDLES
        # (e.g. MomentumEngine.get_momentum()'s own count=6 fetch),
        # atr_normalized_momentum is None — deliberately not backfilled
        # with a shorter/different-period ATR or any other fallback
        # denominator.
        atr_normalized_momentum = None
        if len(candles) >= ATR14_MIN_CANDLES:
            atr14 = compute_atr(candles, period=14)
            if atr14:
                atr_normalized_momentum = slope2 / atr14

        return MomentumSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            momentum=scaled_score,
            slope=round(slope2, 2),
            confidence_drop=confidence_drop,
            score=raw_score,
            atr_normalized_momentum=atr_normalized_momentum,
        )

    def get_momentum(self, symbol: str, timeframe: str, cache=None) -> MomentumSnapshot:
        candles = self.candle_engine.get_snapshots(symbol, timeframe, count=6, cache=cache)
        return self.compute(candles, symbol, timeframe)

candle_engine = CandleEngine()
momentum_engine = MomentumEngine(candle_engine)
