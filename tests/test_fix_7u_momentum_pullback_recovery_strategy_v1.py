"""Fix #7U — Momentum Pullback Recovery v1 baseline: a SEQUENCE
confirmation strategy over canonical atr_normalized_momentum history (a
genuine, earlier, same-direction expansion, followed by a later weak
pullback, followed by the CURRENT reading recovering strong again in that
same direction).

Evidence audit: MomentumEngine.compute() only ever exposes
atr_normalized_momentum "as of right now" -- a single StrategySnapshot
cannot, by itself, prove momentum was previously strong, then weakened,
then recovered. There was no historical momentum series anywhere in
committed code. Fix #7U closes the gap with MomentumEngine.
detect_pullback_recovery(): a pure method that replays self.compute()
(the exact canonical slope2/ATR14 formula, never reimplemented) on
shorter PREFIXES of the SAME already-fetched candle window
StructureEngine already passes to compute() for the current reading --
no new fetch, no second momentum formula, no persistent state.

Threshold provenance (all reused, none guessed):
  - EXPANSION_THRESHOLD (2.0 ATR) is Fix #7O's own audited
    MomentumExpansionStrategy.MOMENTUM_THRESHOLD, reused verbatim.
  - PULLBACK_WEAK_THRESHOLD (0.5 ATR) / RECOVERY_STRONG_THRESHOLD
    (1.0 ATR) reuse core.Output.Output's own canonical momentum display
    bands (Fix #6Z: ATR_MOMENTUM_MODERATE_THRESHOLD / ATR_MOMENTUM_
    STRONG_THRESHOLD) -- the existing canonical definitions of "weak"
    and "strong" momentum already governing live display everywhere
    else in this pipeline.

Direction-flip-during-pullback (explicitly audited, not silently
decided): the pullback test is magnitude-only (abs(momentum) < 0.5),
sign-agnostic -- at that low a magnitude sign is noise, so a small flip
on the pullback candle itself does not disqualify the sequence. A LARGE
opposite-direction reading (>= 2.0 ATR the opposite way) during either
backward scan is different -- a genuine opposite expansion, not noise --
and immediately invalidates the sequence (stale-identity protection,
mirroring Fix #7T's own "nearest first" principle for CHoCH-then-BOS).

This is a v1 BASELINE only -- final pullback depth, recovery threshold,
max bars between stages, opposite-direction excursion policy (the
moderate gray zone between weak and expansion magnitude), and confidence
tuning are explicitly deferred to a later rule audit. These tests lock in
v1's exact behavior, not a claim that the rules are final.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7u_momentum_pullback_recovery_strategy_v1.py -v
"""
import random
import re
from datetime import datetime, timezone

import pytest

from core.CandleEngine import CandleEngine
from core.core_models import CandleSnapshot
from core.MomentumEngine import MomentumEngine
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot


# ---------------------------------------------------------------------------
# Synthetic candle builders (explicit, engineered moves) so the canonical
# slope2/ATR14 formula produces known, verifiable momentum readings when
# replayed. Each timeline was run against the ACTUAL implementation before
# being locked in here, per this repo's established audit practice.
# ---------------------------------------------------------------------------

def _c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100.0, timestamp=str(ts))


def _baseline(price, idx, candles, n=15, jitter=0.3, seed_rng=None):
    rng = seed_rng or random.Random(0)
    for _ in range(n):
        o = price
        price += rng.uniform(-jitter, jitter)
        cl = price
        h = max(o, cl) + 0.5
        l = min(o, cl) - 0.5
        candles.append(_c(o, h, l, cl, idx)); idx += 1
    return price, idx


def _move(price, idx, candles, total, n=3):
    step = total / n
    for _ in range(n):
        o = price
        price += step
        cl = price
        h = max(o, cl) + 0.3
        l = min(o, cl) - 0.3
        candles.append(_c(o, h, l, cl, idx)); idx += 1
    return price, idx


def _flat(price, idx, candles, n, jitter=0.2, seed_rng=None):
    rng = seed_rng or random.Random(0)
    for _ in range(n):
        o = price
        price += rng.uniform(-jitter, jitter)
        cl = price
        h = max(o, cl) + 0.5
        l = min(o, cl) - 0.5
        candles.append(_c(o, h, l, cl, idx)); idx += 1
    return price, idx


def _bullish_sequence_candles():
    rng = random.Random(42)
    candles = []
    price, idx = _baseline(100.0, 0, candles, seed_rng=rng)
    price, idx = _move(price, idx, candles, 9.0, n=3)       # bullish expansion
    price, idx = _flat(price, idx, candles, 4, seed_rng=rng)  # pullback
    price, idx = _flat(price, idx, candles, 25 - len(candles), seed_rng=rng)
    candles = candles[:25]
    price, idx = _move(price, len(candles), candles, 9.0, n=1)  # bullish recovery
    return candles[:26]


def _bearish_sequence_candles():
    rng = random.Random(43)
    candles = []
    price, idx = _baseline(100.0, 0, candles, seed_rng=rng)
    price, idx = _move(price, idx, candles, -9.0, n=3)      # bearish expansion
    price, idx = _flat(price, idx, candles, 4, seed_rng=rng)  # pullback
    price, idx = _flat(price, idx, candles, 25 - len(candles), seed_rng=rng)
    candles = candles[:25]
    price, idx = _move(price, len(candles), candles, -9.0, n=1)  # bearish recovery
    return candles[:26]


def _expansion_only_candles():
    """Bullish expansion, then decays and stays weak forever -- never
    recovers strong again."""
    rng = random.Random(2)
    candles = []
    price, idx = _baseline(100.0, 0, candles, seed_rng=rng)
    price, idx = _move(price, idx, candles, 9.0, n=3)
    while len(candles) < 26:
        price, idx = _flat(price, len(candles), candles, 1, seed_rng=rng)
    return candles[:26]


def _pullback_without_recovery_candles():
    """Bullish expansion, weakens, stays weak/flat through to "now" --
    never recovers strong."""
    rng = random.Random(3)
    candles = []
    price, idx = _baseline(100.0, 0, candles, seed_rng=rng)
    price, idx = _move(price, idx, candles, 9.0, n=3)
    price, idx = _flat(price, idx, candles, 20, seed_rng=rng)
    return candles[:26]


def _opposite_direction_recovery_candles():
    """Bullish expansion, weak pullback, then a genuine STRONG BEARISH
    (opposite) recovery -- no bearish expansion exists anywhere earlier,
    so this must reject."""
    rng = random.Random(4)
    candles = []
    price, idx = _baseline(100.0, 0, candles, seed_rng=rng)
    price, idx = _move(price, idx, candles, 9.0, n=3)
    price, idx = _flat(price, idx, candles, 4, seed_rng=rng)
    price, idx = _flat(price, idx, candles, 25 - len(candles), seed_rng=rng)
    candles = candles[:25]
    price, idx = _move(price, len(candles), candles, -9.0, n=1)
    return candles[:26]


def _stale_old_expansion_candles():
    """Bullish expansion -> an intervening OPPOSITE (bearish) expansion ->
    weak pullback -> bullish recovery. The old bullish expansion must NOT
    pair with the later bullish recovery across the intervening opposite
    expansion."""
    rng = random.Random(5)
    candles = []
    price, idx = _baseline(100.0, 0, candles, seed_rng=rng)
    price, idx = _move(price, idx, candles, 9.0, n=2)        # old bullish expansion
    price, idx = _move(price, idx, candles, -12.0, n=2)      # intervening opposite expansion
    price, idx = _flat(price, idx, candles, 3, seed_rng=rng)  # pullback
    while len(candles) < 25:
        price, idx = _flat(price, len(candles), candles, 1, seed_rng=rng)
    candles = candles[:25]
    price, idx = _move(price, len(candles), candles, 9.0, n=1)  # bullish recovery
    return candles[:26]


# ---------------------------------------------------------------------------
# MomentumEngine.detect_pullback_recovery() — unit-level audit checks,
# run against the actual implementation with explicit synthetic timelines.
# ---------------------------------------------------------------------------

def test_util_bullish_expansion_pullback_recovery_valid():
    me = MomentumEngine(CandleEngine())
    candles = _bullish_sequence_candles()
    result = me.detect_pullback_recovery(candles, "T", "H1")
    assert result["confirmed"] is True
    assert result["direction"] == "Bullish"
    assert result["expansion_index"] < result["pullback_index"] < result["recovery_index"]
    assert result["recovery_index"] == len(candles) - 1
    assert abs(result["expansion_momentum"]) >= 2.0
    assert abs(result["pullback_momentum"]) < 0.5
    assert abs(result["recovery_momentum"]) >= 1.0


def test_util_bearish_mirror_valid():
    me = MomentumEngine(CandleEngine())
    candles = _bearish_sequence_candles()
    result = me.detect_pullback_recovery(candles, "T", "H1")
    assert result["confirmed"] is True
    assert result["direction"] == "Bearish"
    assert result["expansion_index"] < result["pullback_index"] < result["recovery_index"]
    assert result["expansion_momentum"] <= -2.0
    assert result["recovery_momentum"] <= -1.0


def test_util_expansion_only_rejected():
    me = MomentumEngine(CandleEngine())
    candles = _expansion_only_candles()
    result = me.detect_pullback_recovery(candles, "T", "H1")
    assert result["confirmed"] is False


def test_util_pullback_without_recovery_rejected():
    me = MomentumEngine(CandleEngine())
    candles = _pullback_without_recovery_candles()
    result = me.detect_pullback_recovery(candles, "T", "H1")
    assert result["confirmed"] is False


def test_util_opposite_direction_recovery_rejected():
    me = MomentumEngine(CandleEngine())
    candles = _opposite_direction_recovery_candles()
    result = me.detect_pullback_recovery(candles, "T", "H1")
    assert result["confirmed"] is False


def test_util_stale_old_expansion_identity_rejected():
    """An intervening opposite-direction expansion must invalidate the
    sequence -- the old, pre-reversal expansion must never pair with an
    unrelated later same-direction recovery."""
    me = MomentumEngine(CandleEngine())
    candles = _stale_old_expansion_candles()
    result = me.detect_pullback_recovery(candles, "T", "H1")
    assert result["confirmed"] is False


def test_util_pullback_before_expansion_structurally_impossible():
    """The expansion scan only ever looks strictly before pullback_index
    -- a returned expansion_index >= pullback_index is structurally
    impossible, confirmed here rather than merely asserted in prose."""
    me = MomentumEngine(CandleEngine())
    candles = _bullish_sequence_candles()
    result = me.detect_pullback_recovery(candles, "T", "H1")
    assert result["confirmed"] is True
    assert result["expansion_index"] < result["pullback_index"]


def test_util_recovery_before_pullback_structurally_impossible():
    """recovery_index is always len(candles)-1 ("now"); the pullback scan
    only ever looks strictly before it -- a returned pullback_index >=
    recovery_index is structurally impossible."""
    me = MomentumEngine(CandleEngine())
    candles = _bullish_sequence_candles()
    result = me.detect_pullback_recovery(candles, "T", "H1")
    assert result["confirmed"] is True
    assert result["pullback_index"] < result["recovery_index"]
    assert result["recovery_index"] == len(candles) - 1


def test_util_exact_three_distinct_indices():
    me = MomentumEngine(CandleEngine())
    candles = _bullish_sequence_candles()
    result = me.detect_pullback_recovery(candles, "T", "H1")
    indices = {result["expansion_index"], result["pullback_index"], result["recovery_index"]}
    assert len(indices) == 3


def test_util_too_short_window_returns_no_evidence_not_a_crash():
    me = MomentumEngine(CandleEngine())
    candles = _bullish_sequence_candles()[:10]
    result = me.detect_pullback_recovery(candles, "T", "H1")
    assert result["confirmed"] is False


def test_util_deterministic_repeated_evaluation():
    me = MomentumEngine(CandleEngine())
    candles = _bullish_sequence_candles()
    r1 = me.detect_pullback_recovery(candles, "T", "H1")
    r2 = me.detect_pullback_recovery(candles, "T", "H1")
    r3 = me.detect_pullback_recovery(candles, "T", "H1")
    assert r1 == r2 == r3


def test_util_no_cross_symbol_timeframe_contamination():
    """No persistent/shared state exists -- interleaving calls with two
    completely different candle sets (standing in for two different
    symbol/timeframe pairs) must not affect each other's results."""
    me = MomentumEngine(CandleEngine())
    bull = _bullish_sequence_candles()
    bear = _bearish_sequence_candles()

    r_bull_1 = me.detect_pullback_recovery(bull, "AAA_i", "H1")
    r_bear_1 = me.detect_pullback_recovery(bear, "BBB_i", "M15")
    r_bull_2 = me.detect_pullback_recovery(bull, "AAA_i", "H1")
    r_bear_2 = me.detect_pullback_recovery(bear, "BBB_i", "M15")

    assert r_bull_1 == r_bull_2
    assert r_bear_1 == r_bear_2
    assert r_bull_1["direction"] == "Bullish"
    assert r_bear_1["direction"] == "Bearish"


def test_util_no_persistent_state_on_momentum_engine():
    """Source-scan confirmation that detect_pullback_recovery() introduces
    no module-level or instance mutable cache that could leak state
    across calls."""
    import pathlib
    text = pathlib.Path("core/MomentumEngine.py").read_text(encoding="utf-8")
    start = text.index("def detect_pullback_recovery")
    body = text[start:]
    for forbidden in ("global ", "_cache", "_CACHE", "functools.lru_cache", "self._"):
        assert forbidden not in body


def test_util_raw_legacy_momentum_field_never_read():
    """detect_pullback_recovery() must only ever read
    .atr_normalized_momentum (via self.compute(...)), never the legacy
    raw, price-scaled .momentum field. Scoped to a precise regex (a
    literal '.momentum' attribute access NOT followed by '_') so it
    cannot be tripped up by the many legitimate momentum_sequence_*/
    momentum_expansion_*/etc. field names used throughout."""
    import pathlib
    text = pathlib.Path("core/MomentumEngine.py").read_text(encoding="utf-8")
    start = text.index("def detect_pullback_recovery")
    body = text[start:]
    assert re.search(r"\.momentum(?!_)\b", body) is None


# ---------------------------------------------------------------------------
# Strategy-level tests.
# ---------------------------------------------------------------------------

def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        momentum_sequence_confirmed=False, momentum_sequence_direction=None,
        momentum_expansion_index=None, momentum_expansion_timestamp=None, momentum_expansion_value=None,
        momentum_pullback_index=None, momentum_pullback_timestamp=None, momentum_pullback_value=None,
        momentum_recovery_index=None, momentum_recovery_timestamp=None, momentum_recovery_value=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_BULLISH_SEQUENCE = dict(
    momentum_sequence_confirmed=True, momentum_sequence_direction="Bullish",
    momentum_expansion_index=18, momentum_expansion_timestamp="2026-01-01T02:00:00Z", momentum_expansion_value=3.6,
    momentum_pullback_index=24, momentum_pullback_timestamp="2026-01-01T04:00:00Z", momentum_pullback_value=0.02,
    momentum_recovery_index=25, momentum_recovery_timestamp="2026-01-01T05:00:00Z", momentum_recovery_value=1.7,
)
_BEARISH_SEQUENCE = dict(
    momentum_sequence_confirmed=True, momentum_sequence_direction="Bearish",
    momentum_expansion_index=17, momentum_expansion_timestamp="2026-01-02T02:00:00Z", momentum_expansion_value=-3.5,
    momentum_pullback_index=23, momentum_pullback_timestamp="2026-01-02T04:00:00Z", momentum_pullback_value=-0.21,
    momentum_recovery_index=25, momentum_recovery_timestamp="2026-01-02T05:00:00Z", momentum_recovery_value=-4.0,
)


def test_bullish_sequence_valid_long():
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = MomentumPullbackRecoveryStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["trigger"] == "MOMENTUM_PULLBACK_RECOVERY"
    assert result["reason"] == "Bullish Momentum Pullback Recovery"


def test_bearish_sequence_valid_short():
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    snap = _base_snapshot(**_BEARISH_SEQUENCE)
    result = MomentumPullbackRecoveryStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["trigger"] == "MOMENTUM_PULLBACK_RECOVERY"
    assert result["reason"] == "Bearish Momentum Pullback Recovery"


def test_sequence_not_confirmed_rejected():
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    snap = _base_snapshot()
    assert MomentumPullbackRecoveryStrategy().react(snap, {}) is None


def test_neutral_direction_rejected():
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["momentum_sequence_direction"] = None
    snap = _base_snapshot(**overrides)
    assert MomentumPullbackRecoveryStrategy().react(snap, {}) is None


def test_missing_geometry_rejected():
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["momentum_expansion_index"] = None
    overrides["momentum_expansion_timestamp"] = None
    snap = _base_snapshot(**overrides)
    assert MomentumPullbackRecoveryStrategy().react(snap, {}) is None


def test_defensive_ordering_violation_rejected():
    """Strategy-level defense in depth: a hand-built/inconsistent snapshot
    claiming momentum_sequence_confirmed=True with indices out of order
    must still reject, never trusting the flag alone."""
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["momentum_pullback_index"] = overrides["momentum_expansion_index"]
    snap = _base_snapshot(**overrides)
    assert MomentumPullbackRecoveryStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Chart markings: exactly 3 real candle markings, no fabricated geometry.
# ---------------------------------------------------------------------------

def test_exactly_three_real_markings_bullish():
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = MomentumPullbackRecoveryStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 3
    for m in markings:
        validate_chart_marking(m)
        assert m["type"] == "candle"
        assert m["direction"] == "long"

    expansion_marking, pullback_marking, recovery_marking = markings
    assert expansion_marking["label"] == "Momentum Expansion"
    assert expansion_marking["timestamp"] == "2026-01-01T02:00:00Z"
    assert expansion_marking["candle_index"] == 18

    assert pullback_marking["label"] == "Momentum Pullback"
    assert pullback_marking["timestamp"] == "2026-01-01T04:00:00Z"
    assert pullback_marking["candle_index"] == 24

    assert recovery_marking["label"] == "Momentum Recovery"
    assert recovery_marking["timestamp"] == "2026-01-01T05:00:00Z"
    assert recovery_marking["candle_index"] == 25


def test_exactly_three_real_markings_bearish():
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    snap = _base_snapshot(**_BEARISH_SEQUENCE)
    result = MomentumPullbackRecoveryStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 3
    for m in markings:
        validate_chart_marking(m)
        assert m["direction"] == "short"
    assert [m["label"] for m in markings] == ["Momentum Expansion", "Momentum Pullback", "Momentum Recovery"]


def test_no_fabricated_geometry():
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = MomentumPullbackRecoveryStrategy().react(snap, {})
    expansion_marking, pullback_marking, recovery_marking = result["chart_markings"]
    assert expansion_marking["timestamp"] == snap.momentum_expansion_timestamp
    assert expansion_marking["candle_index"] == snap.momentum_expansion_index
    assert pullback_marking["timestamp"] == snap.momentum_pullback_timestamp
    assert pullback_marking["candle_index"] == snap.momentum_pullback_index
    assert recovery_marking["timestamp"] == snap.momentum_recovery_timestamp
    assert recovery_marking["candle_index"] == snap.momentum_recovery_index


# ---------------------------------------------------------------------------
# Confidence: exact formula, bounded.
# ---------------------------------------------------------------------------

def test_confidence_bounded_and_exact_formula():
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["momentum_recovery_value"] = 1.0
    snap = _base_snapshot(**overrides)
    result = MomentumPullbackRecoveryStrategy().react(snap, {})
    assert result["confidence"] == 0.5

    overrides2 = dict(_BULLISH_SEQUENCE)
    overrides2["momentum_recovery_value"] = 1.5
    snap2 = _base_snapshot(**overrides2)
    result2 = MomentumPullbackRecoveryStrategy().react(snap2, {})
    assert result2["confidence"] == 0.75

    overrides3 = dict(_BULLISH_SEQUENCE)
    overrides3["momentum_recovery_value"] = 5.0
    snap3 = _base_snapshot(**overrides3)
    result3 = MomentumPullbackRecoveryStrategy().react(snap3, {})
    assert result3["confidence"] == 1.0

    for r in (result, result2, result3):
        assert 0.0 <= r["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# No duplicate momentum formula; no zone/bias/structure/candle-pattern
# scoring; raw legacy .momentum ignored.
# ---------------------------------------------------------------------------

def test_no_duplicate_momentum_formula_in_strategy():
    import pathlib
    text = pathlib.Path("core/strategy/MomentumPullbackRecoveryStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("compute_atr", "slope2", "ATR14", "atr14"):
        assert forbidden not in text, f"MomentumPullbackRecoveryStrategy.py unexpectedly references {forbidden!r}"


def test_no_zone_bias_structure_or_candle_pattern_scoring():
    import pathlib
    text = pathlib.Path("core/strategy/MomentumPullbackRecoveryStrategy.py").read_text(encoding="utf-8")
    for forbidden in (
        "snapshot.active_zone", "snapshot.mitigated_zone", "snapshot.bias",
        "snapshot.structure_type", "snapshot.structure_direction", "snapshot.structure_valid",
        "snapshot.engulfing", "snapshot.conviction",
    ):
        assert forbidden not in text, f"MomentumPullbackRecoveryStrategy.py unexpectedly reads {forbidden}"


def test_raw_legacy_momentum_field_ignored_in_strategy():
    """Scoped to the react() method body only (not the class docstring,
    which legitimately explains in prose that the legacy `.momentum`
    field is NOT used -- a self-referential false positive otherwise) and
    to a precise regex (literal '.momentum' NOT followed by '_') so the
    many legitimate momentum_sequence_*/momentum_expansion_*/etc. field
    reads don't trip a false positive either."""
    import pathlib
    text = pathlib.Path("core/strategy/MomentumPullbackRecoveryStrategy.py").read_text(encoding="utf-8")
    body = text[text.index("def react("):]
    assert re.search(r"\.momentum(?!_)\b", body) is None
    assert "snapshot.atr_normalized_momentum" not in body


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = MomentumPullbackRecoveryStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_momentum_pullback_recovery_strategy():
    """Originally asserted the discovered count equals exactly 19 -- Fix
    #7V later added a genuinely new 20th strategy
    (SupportResistanceReactionStrategy), which made that exact-count
    snapshot stale (a real, intended addition, not a regression -- see
    tests/test_fix_7v_support_resistance_reaction_strategy_v1.py::test_strategy_engine_discovers_twenty_strategies_now
    for that fix's own count assertion). Rewritten to check the actual
    invariant this test exists for -- MomentumPullbackRecoveryStrategy is
    discovered alongside the original 18 -- rather than a total count that
    any future new strategy would otherwise make stale again."""
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert "MomentumPullbackRecoveryStrategy" in engine.enabled
    existing_eighteen = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy", "CHOCHBOSConfirmationStrategy",
    }
    assert existing_eighteen <= set(engine.enabled.keys())


def test_existing_eighteen_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_eighteen = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy", "CHOCHBOSConfirmationStrategy",
    }
    assert existing_eighteen <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_gracefully():
    """A raw-JSON-body StrategySnapshot(**data) that omits
    momentum_sequence_confirmed falls through to False -- never guessed --
    and the strategy rejects cleanly rather than crashing."""
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
    )
    snap = StrategySnapshot(**base)
    assert snap.momentum_sequence_confirmed is False
    from core.strategy.MomentumPullbackRecoveryStrategy import MomentumPullbackRecoveryStrategy
    assert MomentumPullbackRecoveryStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
