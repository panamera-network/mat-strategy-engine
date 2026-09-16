from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, price_from_snapshot

# Fix #7S — Conviction-Based Selective Entry v1 threshold, chosen after
# auditing the LIVE conviction distribution across the full 36-symbol x
# 9-timeframe universe (StyleSnapshot.conviction, Fix #6AK) rather than
# guessed. Of 324 live (symbol, timeframe) pairs, 261 had no directional
# call at all (conviction pinned at exactly 0.0 by compute_conviction()'s
# own opposition/no-direction floor); the remaining 63 directed readings
# were heavily skewed low (median 0.08, p70 ~0.17) with a clear gap before
# a much smaller cluster from ~0.5 upward (p90 ~0.54, p95 ~0.58, max
# observed 0.83; re-running the same live audit minutes later moved
# individual counts as new candles formed, but the same shape held: a
# sparse gap between ~0.2 and ~0.5). 0.5 sits right at the start of that
# upper cluster and has a second, structural justification: for swing-mode
# conviction, no single component can reach 0.5 alone (weights are capped
# at 0.4/0.3/0.3 -- see StyleSnapshot.compute_conviction()), so a swing
# reading at or above this threshold necessarily reflects at least two
# independently-agreeing components, not one weak signal alone. This is a
# v1 baseline threshold only -- final calibration deferred to a later rule
# audit.
CONVICTION_THRESHOLD = 0.5

_DIRECTION_MAP = {"uptrend": "long", "downtrend": "short"}
_LABEL_MAP = {"uptrend": "Bullish High Conviction", "downtrend": "Bearish High Conviction"}


class ConvictionSelectiveStrategy(Strategy):
    """Fix #7S — Conviction-Based Selective Entry v1: fires only on the
    canonical, already-computed conviction evidence (StyleSnapshot.
    conviction/direction, Fix #6AK -- via StrategySnapshot.conviction/
    conviction_direction, Fix #7S's own additive wiring). This strategy
    never computes conviction itself and never reimplements any part of
    compute_conviction()'s formula -- it only reads the final scalar and
    its paired direction.

    Direction comes ONLY from conviction_direction ("uptrend" -> long,
    "downtrend" -> short); "neutral" (no directional call at all) rejects.
    Raw momentum is never consulted directly for direction -- whatever
    momentum evidence conviction already folded in (the scalping-mode
    momentum term) is exactly what's already reflected in the conviction
    scalar itself.

    Eligibility is conviction >= CONVICTION_THRESHOLD only. No zone
    requirement, no BOS/CHoCH requirement, no candle-pattern requirement,
    and no separate bias/momentum gate beyond whatever compute_conviction()
    already baked in -- conviction's own opposition floor (any conflicting
    component contributes exactly 0, per Fix #6AK) is the only "opposition"
    handling this strategy relies on; it is never re-checked here.

    Confidence is the conviction value itself, unmodified -- compute_
    conviction() already produces a bounded [0,1], direction-relative
    score, so remapping or rescoring it here would only re-derive
    information already present, not add anything."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        direction_label = snapshot.conviction_direction
        if direction_label not in _DIRECTION_MAP:
            # "neutral" (no directional call) and any missing/unrecognized
            # value both reject -- never guessed into a side.
            return None

        conviction = snapshot.conviction
        if conviction is None or conviction < CONVICTION_THRESHOLD:
            return None

        candles = snapshot.recent_candles
        if not candles:
            return None
        current_candle = candles[-1]

        direction = _DIRECTION_MAP[direction_label]
        label = _LABEL_MAP[direction_label]
        confidence = conviction

        marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            timestamp=current_candle.get("timestamp"),
            candle_index=current_candle.get("index"),
            evidence_ref={
                "source": "conviction_selective",
                "conviction": conviction,
                "conviction_direction": direction_label,
            },
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "CONVICTION_SELECTIVE",
            "timestamp": snapshot.timestamp,
            "price": price_from_snapshot(snapshot),
            "chart_markings": [marking],
        }
