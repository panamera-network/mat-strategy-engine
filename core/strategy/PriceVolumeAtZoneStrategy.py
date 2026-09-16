from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import (
    Strategy, StrategySnapshot, strategy_momentum_confidence,
)

# Fix #7R — Price-Volume at Zone v1 baseline confidence formula, reported
# explicitly per this fix's own requirement (base from valid zone +
# participation confirmation only, no bias/structure scoring):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
#
# BASE_CONFIDENCE (0.5) reflects the confirmed canonical evidence itself --
# a valid Demand/Supply zone (active_zone_type) plus a confirmed
# participation state (price direction agrees with volume direction, in
# the zone's favor). MOMENTUM_WEIGHT (0.5) scales the canonical,
# direction-agreement-gated strategy_momentum_confidence() (Fix #6AU) on
# top of that base -- optional support only, never gates eligibility.
# Range: exactly [0.5, 1.0] whenever eligible. Same shape already
# established by BreakoutRetestStrategy (Fix #7P) and MTFBiasCascadeStrategy
# (Fix #7Q) for "canonical confirmation + optional momentum support"
# strategies -- no separate structural/freshness bonus term this time,
# per this fix's own "no bias/structure scoring" requirement.
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5


class PriceVolumeAtZoneStrategy(Strategy):
    """Fix #7R — Price-Volume at Zone v1: zone is WHERE (the canonical
    active Demand/Supply zone, demand_engine.get_active_zone() via
    StrategySnapshot.active_zone_type/top/bottom, Fix #7M's existing
    wiring -- never Support/Resistance evidence), price-vs-volume is the
    QUALITY of the reaction there.

    price direction: the current (most recent) candle's own standalone
    direction, close vs open only -- StrategySnapshot.recent_candles[-1]
    ("bull"/"bear"/"neutral", Fix #7K's existing canonical field). No new
    formula -- this is the same per-candle direction already reused by
    MomentumExpansionStrategy (Fix #7O) and MTFBiasCascadeStrategy (Fix
    #7Q) for "current candle" evidence.

    volume direction: the current candle's own volume (Fix #7R's additive
    `recent_candles[-1]["volume"]`, MT5 tick volume -- see
    core.core_models.CandleDirection's own docstring for the tick-vs-real-
    volume audit) versus the immediately PRIOR candle's volume
    (`recent_candles[-2]["volume"]`). This is a provisional v1 definition
    only -- current-candle-vs-previous-candle, not a rolling baseline or
    any relative-volume window; final volume normalization is explicitly
    deferred to a later rule audit. up: current > previous. down: current
    < previous. Equal volume, or either value missing, produces neither
    state -- rejected, never guessed either way.

    Four raw states (price direction x volume direction): bullish
    participation (price up + volume up), bullish weakening (price up +
    volume down), bearish participation (price down + volume up), bearish
    weakening (price down + volume down). Only the participation states
    are eligible in this v1 baseline:
      - Demand zone: bullish participation -> long. Bearish participation
        rejects outright. Either weakening state does not auto-fire.
      - Supply zone: bearish participation -> short. Bullish participation
        rejects outright. Either weakening state does not auto-fire.
    No bias gate, no BOS/CHoCH hard gate, no raw legacy `.momentum` gate --
    eligibility is zone-type + participation-state + interaction only.

    Interaction gate (Fix #7R's own follow-up audit, before this fix's
    first commit): demand_
    engine.get_active_zone() proves only "nearest valid, not-mitigated
    zone by distance" -- confirmed by explicit test against the real
    selector, it still returns a zone even when the current candle is
    clearly far away from it (distance has no cutoff). It never proves the
    reaction candle actually touches that zone. Price-Volume confirmation
    is only meaningful when the candle producing it genuinely interacts
    with the selected zone, so this strategy additionally requires the
    current candle's own real high/low (StrategySnapshot.current_high/
    current_low -- already exposed, straight copy of the same current
    candle used everywhere else in this file, no new fetch) to overlap
    [active_zone_bottom, active_zone_top]. The overlap test itself
    (candle_low <= zone_top and candle_high >= zone_bottom) is not a new
    formula -- it is the identical wick-inclusive geometric check
    demand_engine.detect_zones() already uses to count zone touch
    episodes; only the input here is the CURRENT candle specifically,
    not zone_type/S&R semantics and not a new distance-based
    substitute."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        zone_type = snapshot.active_zone_type
        if zone_type not in ("demand", "supply"):
            return None
        if snapshot.active_zone_top is None or snapshot.active_zone_bottom is None:
            # Defensive: a genuine active zone always carries real top/
            # bottom geometry -- without it there is nothing real to mark.
            return None
        if snapshot.current_high is None or snapshot.current_low is None:
            return None
        touches_zone = (
            snapshot.current_low <= snapshot.active_zone_top
            and snapshot.current_high >= snapshot.active_zone_bottom
        )
        if not touches_zone:
            # get_active_zone() is a nearest-zone selector, not a
            # touch/interaction proof -- it still returns the same zone
            # even when the current candle is clearly far away from it.
            # Reject rather than evaluate a "reaction" that never happened.
            return None

        candles = snapshot.recent_candles
        if not candles or len(candles) < 2:
            return None
        current_candle = candles[-1]
        previous_candle = candles[-2]

        price_direction = current_candle.get("direction")
        if price_direction not in ("bull", "bear"):
            # "neutral" (open == close) is an explicit real value, not
            # missing evidence -- but it is neither price-up nor
            # price-down, so it cannot satisfy either raw state.
            return None

        current_volume = current_candle.get("volume")
        previous_volume = previous_candle.get("volume")
        if current_volume is None or previous_volume is None:
            return None
        if current_volume > previous_volume:
            volume_direction = "up"
        elif current_volume < previous_volume:
            volume_direction = "down"
        else:
            # Equal volume is an explicit real outcome, not missing
            # evidence -- but it is neither volume-up nor volume-down, so
            # it cannot satisfy either raw state.
            return None

        # Explicit state check (not boolean algebra) -- only the exact
        # participation state for this zone's own side fires. Any other
        # combination (opposite participation, either weakening state)
        # rejects outright / does not auto-fire, per this fix's own
        # eligibility spec.
        if zone_type == "demand":
            if price_direction == "bull" and volume_direction == "up":
                direction = "long"
                label = "Bullish Price-Volume Demand Reaction"
                price = snapshot.active_zone_top
            else:
                return None
        else:
            if price_direction == "bear" and volume_direction == "up":
                direction = "short"
                label = "Bearish Price-Volume Supply Reaction"
                price = snapshot.active_zone_bottom
            else:
                return None

        confidence = round(
            min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction), 1.0),
            2,
        )

        marking = make_chart_marking(
            "zone",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            top=snapshot.active_zone_top,
            bottom=snapshot.active_zone_bottom,
            timestamp=current_candle.get("timestamp"),
            candle_index=current_candle.get("index"),
            evidence_ref={
                "source": "price_volume_at_zone",
                "zone_type": zone_type,
                "price_direction": price_direction,
                "volume_direction": volume_direction,
                "current_volume": current_volume,
                "previous_volume": previous_volume,
            },
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "PRICE_VOLUME_AT_ZONE",
            "timestamp": snapshot.timestamp,
            "price": price,
            "chart_markings": [marking],
        }
