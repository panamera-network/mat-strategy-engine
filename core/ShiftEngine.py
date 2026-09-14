from datetime import datetime, timezone
import math
from typing import Optional
from core.CandleEngine import CandleEngine
from core.core_models import BiasShiftEvent, StructureSnapshot


from datetime import datetime, timezone
from typing import Optional
from core.CandleEngine import CandleEngine
from core.core_models import BiasShiftEvent, StructureSnapshot


class ShiftEngine:
    SHIFT_COLORS = {
        "Bullish": "#00ff00",  # vivid green
        "Bearish": "#ff0000",  # vivid red
        "Neutral": "#cccccc"   # gray
    }

    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine
        self.current_shift_direction = {}
        self.last_shift_change = {}

    def detect_zone_interaction(self, snapshot: StructureSnapshot, tf: str, conviction: Optional[float] = None, cache=None) -> dict:
        """Fix #6D — canonical name for what this method has always actually
        computed (per Fix #6A/#6B's audit): a single candle's wick reaching
        a demand/supply zone's proximal edge. This is a price/zone-proximity
        signal, not a structural one — it does not read BOS/CHoCH, swing
        HH/HL/LH/LL, or momentum/displacement, and CHoCH is deliberately not
        consulted here (that's `structural_shift`, a separate, already-
        existing concept on StructureSnapshot — see Fix #6B). Detection
        formula is byte-for-byte unchanged from the pre-rename
        implementation, only the name (and the local variable names below,
        for clarity) changed.

        Fix #6AJ — this is now a thin composition of two independently
        callable steps: _detect_interaction_evidence() (pure detection, no
        conviction dependency at all) and build_zone_interaction_result()
        (conviction-based colorization only). Behavior, keys, values, the
        single 1-candle fetch, and bookkeeping timing are all byte-for-byte
        unchanged — this split does not reorder anything in StyleEngine.py
        and does not touch conviction's own formula (see Fix #6AI's audit,
        which this split implements the first half of)."""
        evidence = self._detect_interaction_evidence(snapshot, tf, cache=cache)
        return self.build_zone_interaction_result(evidence, conviction)

    def _detect_interaction_evidence(self, snapshot: StructureSnapshot, tf: str, cache=None) -> dict:
        """Fix #6AJ — pure detection step, extracted unchanged from the
        pre-split detect_zone_interaction(): the same single 1-candle
        cached fetch, the same zone/level/epsilon check, and the same
        bookkeeping (current_shift_direction/last_shift_change) update
        timing -- bookkeeping is updated only on the full-evidence path,
        skipped on the no-candle / no-zone-or-level early returns, exactly
        as before. No conviction parameter exists on this method at all --
        detection evidence is independent of conviction by construction,
        not just by convention."""
        candles = self.candle_engine.get_snapshots(symbol=snapshot.symbol, tf=tf, count=1, cache=cache)
        if not candles:
            return self._evidence(False, "Neutral", "neutral", None)

        candle = candles[-1]
        zone = snapshot.context_zone
        level = snapshot.context_level

        if not zone or level is None:
            return self._evidence(False, "Neutral", "neutral", None)

        epsilon = 0.0002
        interacted = False
        interaction_direction = "Neutral"

        if zone in ["demand", "support"] and candle.low <= level + epsilon:
            interacted = True
            interaction_direction = "Bullish"
        elif zone in ["supply", "resistance"] and candle.high >= level - epsilon:
            interacted = True
            interaction_direction = "Bearish"

        key = (snapshot.symbol, tf)
        prev_direction = self.current_shift_direction.get(key)
        if prev_direction != interaction_direction:
            self.last_shift_change[key] = datetime.now(timezone.utc)
        self.current_shift_direction[key] = interaction_direction

        return self._evidence(interacted, interaction_direction, zone, level)

    def _evidence(self, interacted: bool, interaction_direction: str, zone_type: str, level: Optional[float]) -> dict:
        """Fix #6AJ — the exact evidence shape requested: interacted,
        interaction_direction, zone_type, level, plus the legacy
        shifted/shift_direction aliases (same values, old names) so
        build_zone_interaction_result() doesn't need to re-derive them."""
        return {
            "interacted": interacted,
            "interaction_direction": interaction_direction,
            "zone_type": zone_type,
            "level": level,
            "shifted": interacted,
            "shift_direction": interaction_direction,
        }

    def build_zone_interaction_result(self, evidence: dict, conviction: Optional[float] = None) -> dict:
        """Fix #6AJ — public colorization/build step: takes detection
        evidence (from _detect_interaction_evidence(), or any dict with the
        same shape) plus an optional conviction, and returns the full
        result dict (canonical + legacy keys, conviction-scaled colors).
        Performs no detection and no candle fetch of its own -- pure color
        derivation on already-known evidence, via the same _build_result()/
        _conviction_color() this module has always used."""
        return self._build_result(
            evidence["interacted"], evidence["interaction_direction"],
            evidence["zone_type"], evidence["level"], conviction,
        )

    def detect_shift(self, snapshot: StructureSnapshot, tf: str, conviction: Optional[float] = None, cache=None) -> dict:
        """Fix #6D — legacy name, kept as a thin alias so existing callers
        (StyleEngine.py at the time of writing) don't break. Prefer
        detect_zone_interaction() in new code; this delegates to it
        unchanged."""
        return self.detect_zone_interaction(snapshot, tf, conviction=conviction, cache=cache)

    def _build_result(self, interacted: bool, interaction_direction: str, zone: str, level: Optional[float], conviction: Optional[float]):
        color = self._conviction_color(interaction_direction, conviction)
        return {
            # Fix #6D — canonical keys.
            "zone_interaction": interacted,
            "zone_interaction_direction": interaction_direction,
            "zone_interaction_color": color,
            "zone_type": zone,
            "level": level,
            # Fix #6D — legacy aliases/mirrors, same values under the old
            # names. Kept temporarily so existing diagnostic/alignment
            # consumers reading these keys are unaffected by this rename.
            "shifted": interacted,
            "shift_direction": interaction_direction,
            "shift_color": color,
        }

    def _conviction_color(self, shift_direction: str, conviction: Optional[float]) -> str:
        base_color = self.SHIFT_COLORS[shift_direction]
        if shift_direction == "Neutral" or conviction is None:
            return base_color

        # Clamp conviction between 0 and 1
        conviction = max(0.0, min(1.0, conviction))

        # Non-linear scaling: ease-out curve
        # Low conviction → small brightness, high conviction → big jump
        brightness_factor = 0.4 + (math.sqrt(conviction) * 0.6)  # 40%–100%

        return self._adjust_brightness(base_color, brightness_factor)


    def _adjust_brightness(self, hex_color: str, factor: float) -> str:
        hex_color = hex_color.lstrip("#")
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        r = min(255, int(r * factor))
        g = min(255, int(g * factor))
        b = min(255, int(b * factor))
        return f"#{r:02x}{g:02x}{b:02x}"

    def get_last_shift_change_time(self, symbol: str, tf: str) -> Optional[datetime]:
        return self.last_shift_change.get((symbol, tf))
    
def detect_bias_shift(prev_bias: str, snapshot: StructureSnapshot, symbol: str) -> Optional[BiasShiftEvent]:

        if snapshot.structure not in {"breakout", "reversal", "trend"}:
            return None  # Only shift on meaningful structural zones

        if not snapshot.structure_valid:
            print(f"{symbol} structure invalid — skipping shift detection")
            return None

        suppression = [snapshot.suppression_reason] if snapshot.suppression else []

        return BiasShiftEvent(
            symbol=symbol,
            timeframe=snapshot.timeframe,
            previous_bias=prev_bias,
            new_bias=snapshot.bias,
            confirmed=not snapshot.suppression,
            timestamp=snapshot.timestamp.isoformat(),
            zone=snapshot.context_zone,
            structure=snapshot.structure,
            direction=snapshot.structure_direction,
            momentum=snapshot.momentum,
            confidence_drop=snapshot.confidence_drop,
            suppression=suppression,
            trigger=snapshot.structure_type
        )



