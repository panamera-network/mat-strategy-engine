from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import Strategy, StrategySnapshot, strategy_momentum_confidence

# Fix #7T — CHoCH -> BOS Confirmation v1 baseline confidence formula,
# reported explicitly per this fix's own requirement (base from a valid
# CHoCH->BOS sequence only, no zone/bias scoring):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
#
# BASE_CONFIDENCE (0.5) reflects the confirmed canonical evidence itself --
# a genuine, sequence-ordered CHoCH followed by a later, same-direction BOS
# (StrategySnapshot.choch_confirmed, Fix #7T's own additive wiring).
# MOMENTUM_WEIGHT (0.5) scales the canonical, direction-agreement-gated
# strategy_momentum_confidence() (Fix #6AU) on top of that base -- optional
# support only, never gates eligibility. Range: exactly [0.5, 1.0] whenever
# eligible. Same shape already established by BreakoutRetestStrategy
# (Fix #7P) and MTFBiasCascadeStrategy (Fix #7Q) for "canonical
# confirmation + optional momentum support" strategies.
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5


class CHOCHBOSConfirmationStrategy(Strategy):
    """Fix #7T — CHoCH -> BOS Confirmation v1: a SEQUENCE confirmation
    strategy, not "current BOS + current trend" collapsed into one check.
    Eligibility requires ALL of:
      - the CURRENT structure event (structure_type/structure_direction/
        structure_valid) is itself a confirmed, valid BOS,
      - StrategySnapshot.choch_confirmed is True -- a genuine, earlier,
        SAME-DIRECTION CHoCH was found strictly before the current event
        (Fix #7T's upstream sequence-evidence wiring, which replays the
        same canonical swing/structure classification helpers already
        used for the single "current event" -- see core.structure_utils's
        own docstring for the full audit rationale -- on shorter prefixes
        of the same already-fetched lookback window; never inferred from
        the current BOS's fields alone, never reconstructed from
        unrelated snapshot fields, and never a second, independent
        BOS/CHoCH classification performed by this strategy itself).

    A BOS with no prior CHoCH, a CHoCH with no later BOS (current event
    itself is a CHoCH, not a BOS), a BOS that happens to precede an
    unrelated CHoCH, and an opposite-direction CHoCH/BOS pairing are all
    rejected upstream, by construction -- the sequence evidence only ever
    populates choch_confirmed when the current event IS a valid BOS, the
    CHoCH strictly precedes it (same-candle collision is structurally
    impossible), and the CHoCH's own direction matches the BOS's
    direction. No zone requirement, no candle-pattern requirement, no
    separate bias gate -- and no strategy-local mutable memory: every
    input is a pure, already-computed field on this single snapshot, so
    repeated evaluation of the same snapshot is always deterministic and
    carries nothing across symbols or timeframes.

    BOS marking identity (Fix #7T's own follow-up audit, before this
    fix's first commit): the "later BOS" marking uses bos_origin_index/
    bos_origin_timestamp -- the true origin of the CURRENT BOS leg (Fix
    #7P's own current-leg backward-origin principle) -- never event_
    index/event_timestamp, which always describe "now" and can be several
    candles later than where this leg actually began. Explicit testing
    against 5 named timelines (a single-candle BOS, a BOS with several
    trailing closes beyond the level, a failed-then-renewed breakout, a
    full opposite reversal before a same-direction re-confirmation, and a
    wick-only touch before the real close-break) confirmed choch_index
    always ends up strictly before bos_origin_index too, even though the
    CHoCH search itself was never changed to scan relative to it."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if not snapshot.structure_valid or snapshot.structure_type != "BOS":
            return None
        if snapshot.structure_direction not in ("Bullish", "Bearish"):
            return None
        if not snapshot.choch_confirmed:
            return None
        if (
            snapshot.bos_origin_index is None
            or snapshot.bos_origin_timestamp is None
            or snapshot.choch_index is None
        ):
            # Defensive: choch_confirmed=True should never appear without
            # this geometry (the upstream sequence-evidence wiring only
            # ever sets them together), but never fabricate a marking if
            # it somehow does.
            return None
        if snapshot.bos_origin_index <= snapshot.choch_index:
            # Defensive, matching BreakoutRetestStrategy's own ordering
            # check (Fix #7P): a genuine sequence requires the BOS leg's
            # true origin strictly AFTER the CHoCH's -- the upstream
            # sequence evidence already enforces this (Fix #7T's own
            # ordering-invariant audit), but never trusts choch_confirmed
            # alone without re-checking the ordering it implies.
            return None

        direction = "long" if snapshot.structure_direction == "Bullish" else "short"
        choch_label = "Bullish CHoCH" if direction == "long" else "Bearish CHoCH"
        bos_label = "Bullish BOS Confirmation" if direction == "long" else "Bearish BOS Confirmation"

        choch_marking = make_chart_marking(
            "structure",
            type(self).__name__,
            snapshot.timeframe,
            choch_label,
            direction=direction,
            price=snapshot.choch_broken_level,
            timestamp=snapshot.choch_timestamp,
            candle_index=snapshot.choch_index,
            evidence_ref={"source": "choch_then_bos", "role": "prior_choch"},
        )
        bos_marking = make_chart_marking(
            "structure",
            type(self).__name__,
            snapshot.timeframe,
            bos_label,
            direction=direction,
            price=snapshot.event_broken_level,
            # Fix #7T (BOS origin identity audit) — the true origin of the
            # current BOS leg, never event_timestamp/event_index (which
            # always describe "now" and can be several candles later than
            # where this leg actually began -- the same "now" vs true-
            # origin gap Fix #7P's own audit found and fixed).
            timestamp=snapshot.bos_origin_timestamp,
            candle_index=snapshot.bos_origin_index,
            evidence_ref={"source": "choch_then_bos", "role": "later_bos"},
        )

        confidence = round(
            min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction), 1.0),
            2,
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": bos_label,
            "confidence": confidence,
            "trigger": "CHOCH_BOS_CONFIRMATION",
            "timestamp": snapshot.timestamp,
            "price": snapshot.event_broken_level,
            "chart_markings": [choch_marking, bos_marking],
        }
