from datetime import datetime, timezone
from typing import List, Optional

from core.CandleEngine import CandleEngine
from core.demand_engine import DemandEngine
from core.FVGEngine import detect_fvg
from core.MomentumEngine import MomentumEngine
from core.OrderBlockEngine import detect_order_blocks
from core.StrengthEngine import StrengthEngine
from core.SuppressionEngine import detect_suppression
from core.core_models import PriceSnapshot, StructureSnapshot
from core.structure_utils import (
    SWING_LOOKBACK,
    SWING_WINDOW,
    detect_structure_event,
    detect_trend,
    derive_snr_levels,
    find_swings,
    label_swing_points,
)

candle_engine = CandleEngine()
momentum_engine = MomentumEngine(candle_engine)
strength_engine = StrengthEngine()

FETCH_COUNT = SWING_LOOKBACK + SWING_WINDOW * 2  # buffer so the lookback window is fully confirmable


# ─────────────────────────────────────────────
# 🧠 Structure Engine
class StructureEngine:
    def __init__(self, candle_engine: CandleEngine, demand_engine: Optional[DemandEngine] = None):
        self.candle_engine = candle_engine
        # Optional — injected by the composition root (api/core_router.py).
        # context_zone/context_level now come exclusively from DemandEngine's
        # canonical get_context() (Fix #4C). The old 2-candle detect_snd()
        # heuristic this used to call has since been removed entirely
        # (Fix #4E1). If no demand_engine is injected, context degrades to
        # ("neutral", None) rather than detecting independently.
        self.demand_engine = demand_engine

    def get_snapshot(self, symbol: str, tf: str, cache=None, zones=None) -> Optional[StructureSnapshot]:
        candles = self.candle_engine.get_snapshots(symbol, tf, count=FETCH_COUNT, cache=cache)
        if len(candles) < SWING_WINDOW * 2 + 1:
            return None

        lookback = candles[-SWING_LOOKBACK:] if len(candles) > SWING_LOOKBACK else candles
        swing_highs, swing_lows = find_swings(lookback)
        structure_event = detect_structure_event(lookback, swing_highs, swing_lows)
        swing_points = label_swing_points(lookback, swing_highs, swing_lows)
        snr_levels = derive_snr_levels(lookback, swing_highs, swing_lows, structure_event)
        order_blocks = detect_order_blocks(lookback, [structure_event], timeframe=tf)
        fvg = detect_fvg(lookback, timeframe=tf)

        # Fix #2 — event index/timestamp evidence, derived independently
        # here so this evidence works standalone. None when there's no
        # valid event, same as broken_level.
        event_index = structure_event.get("index") if structure_event.get("valid") else None
        event_timestamp = (
            str(lookback[event_index].timestamp)
            if isinstance(event_index, int) and 0 <= event_index < len(lookback)
            else None
        )

        prev, curr = candles[-2], candles[-1]
        price = PriceSnapshot(
            symbol=symbol,
            timeframe=tf,
            high=curr.high,
            low=curr.low,
            prev_high=prev.high,
            prev_low=prev.low
        )

        # Fix #4C — canonical context_zone/context_level, via DemandEngine's
        # get_context() (same call, same cache, no separate computation of
        # our own). The old detect_snd() heuristic this replaced has been
        # removed entirely (Fix #4E1), not just unused.
        # Fix #4D3 — optional `zones` (a caller-precomputed zone list, e.g.
        # Output.py's request-scoped zones_map[tf]) is passed straight
        # through so get_context() can skip its own detect_zones() call.
        # None (every caller besides Output.py) behaves exactly as before.
        if self.demand_engine is not None:
            context_zone, context_level = self.demand_engine.get_context(symbol, tf, cache=cache, zones=zones)
        else:
            context_zone, context_level = "neutral", None

        snapshot = StructureSnapshot(
            symbol=symbol,
            timeframe=tf,
            current_high=price.high,
            current_low=price.low,
            prev_high=price.prev_high,
            prev_low=price.prev_low,
            current_zone="Neutral",
            prev_zone="Neutral",
            momentum=0.0,
            timestamp=datetime.now(timezone.utc),
            context_zone=context_zone,
            context_level=context_level,
            snr_levels=snr_levels,
            order_blocks=order_blocks,
            fvg=fvg,
            swing_points=swing_points,
            event_broken_level=structure_event.get("broken_level"),
            event_index=event_index,
            event_timestamp=event_timestamp,
        )

        snapshot.structure_type = structure_event["type"]
        snapshot.structure_direction = structure_event["direction"]
        snapshot.structure_valid = structure_event["valid"]

        momentum_snapshot = momentum_engine.compute(candles, symbol, tf)
        snapshot.momentum = momentum_snapshot.momentum
        snapshot.confidence_drop = momentum_snapshot.confidence_drop

        strength_diag = strength_engine.compute_strength(candles)
        snapshot.strength = strength_diag.strength
        snapshot.body_ratio = strength_diag.avg_body_ratio
        snapshot.momentum_slope = strength_diag.momentum_slope

        suppression_reason = detect_suppression(snapshot)
        snapshot.suppression_reason = suppression_reason or ""
        snapshot.suppression = suppression_reason is not None

        structure_map = {
            "BOS": "breakout",
            "CHOCH": "reversal",
        }
        snapshot.structure = structure_map.get(snapshot.structure_type, "neutral")

        return snapshot

    def batch_snapshots(self, symbols: List[str], tf: str, cache=None) -> List[StructureSnapshot]:
        results = []
        for symbol in symbols:
            snapshot = self.get_snapshot(symbol, tf, cache=cache)
            if snapshot and snapshot.structure_valid:
                results.append(snapshot)
        return results
