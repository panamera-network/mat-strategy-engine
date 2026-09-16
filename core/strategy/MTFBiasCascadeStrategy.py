from typing import Dict, Optional, Tuple

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, price_from_snapshot, strategy_momentum_confidence

# Fix #7Q — canonical, ordered timeframe sequence. Mirrors mt5.constants.
# TIMEFRAMES and core.Output.diagnostic_models.BIAS_ORDER (SCALPING_ORDER +
# SWING_ORDER) -- both identical sequences already used throughout the
# live pipeline (Output.py builds one StructureSnapshot/StrategySnapshot
# per symbol for every one of these timeframes, keyed exactly this way).
# Defined once here, centrally, rather than importing from core.Output
# (a higher assembly layer that already imports FROM core.strategy --
# importing the other way would invert that dependency for no benefit,
# since this is just a plain, dependency-free list) or from mt5.constants
# (which would work but ties a pure strategy-layer concept to the mt5
# package's constants module for a single list literal). Any future
# Strategy needing a higher/lower timeframe neighbor should reuse
# _cascade_timeframes() below rather than hardcoding its own mapping.
_CANONICAL_TIMEFRAME_ORDER = ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1")


def _cascade_timeframes(timeframe: str) -> Optional[Tuple[str, str, str]]:
    """Returns (higher_tf, current_tf, lower_tf) for a fixed 3-timeframe
    cascade centered on `timeframe`, using the canonical ordered sequence
    above -- the immediate neighbors in that sequence, not a hand-picked
    "natural" pairing. This deliberately does NOT match every informal
    example sometimes given for MTF cascades (e.g. "H1 -> H4/H1/M15"): per
    the actual canonical order, H1's immediate lower neighbor is M30, not
    M15 -- M15 is two steps below H1. Using the real sequence instead of a
    hardcoded example is the whole point of auditing the engine's
    canonical timeframe order first rather than assuming a common
    trading-convention grouping.

    Returns None when `timeframe` is not in the canonical sequence, or
    sits at either edge of it (M1 has no lower neighbor, MN1 has no higher
    one) -- v1 requires all 3 timeframes to exist; edge timeframes are out
    of scope for v1 rather than silently degrading to a 2-timeframe
    check."""
    if timeframe not in _CANONICAL_TIMEFRAME_ORDER:
        return None
    idx = _CANONICAL_TIMEFRAME_ORDER.index(timeframe)
    if idx == 0 or idx == len(_CANONICAL_TIMEFRAME_ORDER) - 1:
        return None
    return _CANONICAL_TIMEFRAME_ORDER[idx + 1], timeframe, _CANONICAL_TIMEFRAME_ORDER[idx - 1]


# Fix #7Q — MTF Bias Cascade v1 baseline confidence formula, reported
# explicitly per this fix's own requirement (no structure/zone scoring):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
#
# BASE_CONFIDENCE (0.5) reflects the confirmed canonical evidence itself --
# full 3-timeframe bias agreement (higher, current, and lower all
# independently reading the same canonical .bias direction -- Fix #7C's
# corrected wiring). MOMENTUM_WEIGHT (0.5) scales the canonical,
# direction-agreement-gated strategy_momentum_confidence() (Fix #6AU) on
# top of that base -- optional support only, never gates eligibility.
# Range: exactly [0.5, 1.0] whenever eligible. Same shape already
# established by StructureReversalStrategy (Fix #7H) and
# BreakoutRetestStrategy (Fix #7P) for "canonical confirmation +
# optional momentum support" strategies.
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5


class MTFBiasCascadeStrategy(Strategy):
    """Fix #7Q — MTF Bias Cascade v1: a fixed 3-timeframe (higher/current/
    lower, per the canonical timeframe sequence) canonical .bias agreement
    check. This is deliberately NOT the existing Alignment score
    (core.Output.alignment_signal.compute_alignment_signal(), a weighted,
    multi-timeframe scoring mechanism reading a different field --
    .direction, not .bias -- on a different snapshot type) -- it consumes
    only the canonical bias direction already on StrategySnapshot (Fix
    #7C's corrected wiring), via the SAME context dict every Strategy
    plugin already receives (keyed f"{symbol}_{tf}" for every BIAS_ORDER
    timeframe -- see core/Output/Output.py::_build_strategy_signals()).
    No new evidence wiring was needed for this fix at all.

    Eligibility: all 3 selected timeframes must have a snapshot in
    context, and all 3 must independently read the SAME bias direction
    (all Bullish -> long, all Bearish -> short). Any Neutral, missing
    timeframe, or disagreement is rejected -- no partial-agreement
    scoring in this v1 baseline. No zone, structure, candle-pattern, or
    raw momentum gate."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        cascade = _cascade_timeframes(snapshot.timeframe)
        if cascade is None:
            return None
        higher_tf, current_tf, lower_tf = cascade

        higher_snap = context.get(f"{snapshot.symbol}_{higher_tf}")
        lower_snap = context.get(f"{snapshot.symbol}_{lower_tf}")
        if higher_snap is None or lower_snap is None:
            return None

        higher_bias, current_bias, lower_bias = higher_snap.bias, snapshot.bias, lower_snap.bias

        if higher_bias == "Bullish" and current_bias == "Bullish" and lower_bias == "Bullish":
            direction = "long"
            label = "Bullish MTF Bias Cascade"
        elif higher_bias == "Bearish" and current_bias == "Bearish" and lower_bias == "Bearish":
            direction = "short"
            label = "Bearish MTF Bias Cascade"
        else:
            return None

        # Fix #7K's recent_candles already exposes the current (most
        # recent) candle's real index/timestamp -- no new wiring, no new
        # fetch. Same pattern as MomentumExpansionStrategy (Fix #7O).
        if not snapshot.recent_candles:
            return None
        current_candle = snapshot.recent_candles[-1]

        momentum_term = strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction)
        confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * momentum_term, 1.0), 2)

        marking = make_chart_marking(
            "candle",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            timestamp=current_candle.get("timestamp"),
            candle_index=current_candle.get("index"),
            evidence_ref={
                "source": "mtf_bias_cascade",
                higher_tf: higher_bias,
                current_tf: current_bias,
                lower_tf: lower_bias,
            },
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "MTF_BIAS_CASCADE",
            "timestamp": snapshot.timestamp,
            "price": price_from_snapshot(snapshot),
            "chart_markings": [marking],
        }
