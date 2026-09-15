from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, price_from_snapshot

# Fix #7O — Momentum Expansion v1 baseline eligibility threshold and
# confidence formula, both reported explicitly per this fix's own
# requirement, chosen from an empirical audit rather than guessed:
#
# Audit (live, 2026-09-15, all 36 canonical SYMBOLS x all 9 canonical
# TIMEFRAMES = 324 pairs, zero missing -- atr_normalized_momentum was
# available on every single pair):
#   |atr_normalized_momentum| distribution -- min=0.00 max=6.83 mean=1.05
#   median=0.78 p90=2.26 p95=3.11 p97=3.70 p99=5.27.
#   Eligible-fraction at candidate thresholds: 1.0 ATR -> 38.9%,
#   1.5 ATR -> 21.6%, 2.0 ATR -> 13.0% (~p90).
#
# MOMENTUM_THRESHOLD = 2.0 was chosen for two independent reasons, not
# picked in isolation: (1) it empirically sits at roughly the 90th
# percentile of live cross-sectional |atr_normalized_momentum| -- genuinely
# elevated, not an everyday reading; (2) it is the SAME reference point
# strategy_momentum_confidence() (Fix #6AT/#6AU, used by 6 other live
# strategies) already treats as its own saturation cap -- reusing it here
# means "eligible for Momentum Expansion" lines up with "already at the
# canonical formula's own definition of maximally-confident momentum",
# not an independently invented number.
#
# Confidence deliberately does NOT reuse strategy_momentum_confidence()
# unmodified here: that function saturates at exactly 2.0 ATR, which is
# this strategy's own eligibility floor -- reusing it verbatim would make
# every eligible signal's confidence a flat, non-varying 1.0, failing to
# reflect that momentum can be stronger or weaker even among eligible
# candidates. Instead confidence scales from the eligibility floor up to
# a saturation point of 2x that floor (4.0 ATR -- between the audit's own
# p97=3.70 and p99=5.27, i.e. still an empirically "very strong" region,
# derived from the threshold itself via a fixed, documented multiplier,
# not a second independently-chosen magic number):
#
#   confidence = round(min(abs(atr_normalized_momentum) / (MOMENTUM_THRESHOLD * CONFIDENCE_SATURATION_MULTIPLIER), 1.0), 2)
#
# Range: exactly [0.5, 1.0] whenever eligible (0.5 at the threshold
# boundary itself, rising to 1.0 at 4.0 ATR and beyond). No structure,
# bias, or zone bonus of any kind -- magnitude of canonical momentum is
# the only input.
MOMENTUM_THRESHOLD = 2.0
CONFIDENCE_SATURATION_MULTIPLIER = 2.0


class MomentumExpansionStrategy(Strategy):
    """Fix #7O — Momentum Expansion v1: a momentum-only strategy consuming
    canonical atr_normalized_momentum directly (never the legacy raw
    `.momentum` field, never a price-unit threshold). Eligibility is a
    single ATR-normalized magnitude gate; no zone, structure, bias, or
    candle-pattern requirement.

    IMPORTANT (v1 scope, explicitly not a claim this fix does not make):
    this measures strong CURRENT momentum at the moment of evaluation --
    it is NOT a proven weak-to-strong expansion over time. Detecting an
    actual expansion (momentum increasing from a prior, weaker reading)
    would require comparing against a previous snapshot, which this fix
    deliberately does not do -- there is no historical/prior-snapshot
    state anywhere in this strategy. Stateful weak->strong / threshold-
    crossing semantics are explicitly deferred to a later rule audit.
    """

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        momentum = snapshot.atr_normalized_momentum
        if momentum is None:
            return None

        if momentum >= MOMENTUM_THRESHOLD:
            direction = "long"
            label = "Bullish Momentum Expansion"
        elif momentum <= -MOMENTUM_THRESHOLD:
            direction = "short"
            label = "Bearish Momentum Expansion"
        else:
            return None

        # Fix #7K's recent_candles already exposes the current (most
        # recent) candle's real index/timestamp -- no new wiring needed,
        # no new fetch. atr_normalized_momentum is only ever non-None once
        # MomentumEngine had >=15 candles for a genuine ATR14, well above
        # the 3 candles label_recent_candles() needs, so this is
        # effectively always populated whenever eligibility is reached;
        # the guard below is defensive, not expected to fire live.
        if not snapshot.recent_candles:
            return None
        current_candle = snapshot.recent_candles[-1]

        confidence = round(min(abs(momentum) / (MOMENTUM_THRESHOLD * CONFIDENCE_SATURATION_MULTIPLIER), 1.0), 2)

        marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            timestamp=current_candle.get("timestamp"),
            candle_index=current_candle.get("index"),
            evidence_ref={
                "source": "recent_candles",
                "timeframe": snapshot.timeframe,
                "atr_normalized_momentum": momentum,
            },
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "MOMENTUM_EXPANSION",
            "timestamp": snapshot.timestamp,
            "price": price_from_snapshot(snapshot),
            "chart_markings": [marking],
        }
