"""Fix #6Z — targeted tests for the momentum display band/color migration
to canonical atr_normalized_momentum (Fix #6X/#6Y's audit conclusion:
< 0.5 ATR = weak, [0.5, 1.0) ATR = moderate, >= 1.0 ATR = strong).

Scope: ONLY momentum_band migrates. StyleSnapshot.momentum (legacy raw
score), momentum_color, alignment's +/-0.3 check, conviction's /10 term,
momentum_conf, and signal_health are all untouched by this fix — tests
below explicitly confirm they still read the legacy raw value.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_momentum_band_atr_migration.py -v
"""
from core.Output.Output import (
    _momentum_band,
    ATR_MOMENTUM_MODERATE_THRESHOLD,
    ATR_MOMENTUM_STRONG_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Canonical band boundaries
# ---------------------------------------------------------------------------

def test_constants_match_canonical_bands():
    assert ATR_MOMENTUM_MODERATE_THRESHOLD == 0.5
    assert ATR_MOMENTUM_STRONG_THRESHOLD == 1.0


def test_plus_and_minus_0_49_is_weak():
    assert _momentum_band(0.49) == "weak"
    assert _momentum_band(-0.49) == "weak"


def test_plus_and_minus_0_5_is_moderate():
    assert _momentum_band(0.5) == "moderate"
    assert _momentum_band(-0.5) == "moderate"


def test_plus_and_minus_0_99_is_moderate():
    assert _momentum_band(0.99) == "moderate"
    assert _momentum_band(-0.99) == "moderate"


def test_plus_and_minus_1_0_is_strong():
    assert _momentum_band(1.0) == "strong"
    assert _momentum_band(-1.0) == "strong"


def test_large_magnitude_both_directions_is_strong():
    assert _momentum_band(5.53) == "strong"
    assert _momentum_band(-5.53) == "strong"


def test_bullish_bearish_equal_magnitude_same_band():
    for v in (0.1, 0.49, 0.5, 0.75, 0.99, 1.0, 2.41, 5.53):
        assert _momentum_band(v) == _momentum_band(-v)


# ---------------------------------------------------------------------------
# None behavior explicit
# ---------------------------------------------------------------------------

def test_none_returns_none_not_weak():
    assert _momentum_band(None) is None


def test_zero_is_weak_not_none():
    """Zero is a real, known value (no movement) -- must not be confused
    with None (canonical value unavailable)."""
    assert _momentum_band(0.0) == "weak"


# ---------------------------------------------------------------------------
# StyleSnapshot / StyleEngine wiring (synthetic)
# ---------------------------------------------------------------------------

def test_style_snapshot_carries_atr_normalized_momentum_field():
    from core.core_models import StyleSnapshot

    snap = StyleSnapshot(
        symbol="TEST", timeframe="M15", mode="scalping",
        direction="neutral", momentum=0.0004, bias=0.0,
    )
    assert snap.atr_normalized_momentum is None  # default
    snap.atr_normalized_momentum = 1.32
    assert snap.atr_normalized_momentum == 1.32
    assert snap.momentum == 0.0004  # legacy field untouched by the new one


def test_get_style_snapshot_reuses_structure_atr_normalized_momentum():
    from core.StyleEngine import get_style_snapshot

    class FakeStructure:
        context_zone = "neutral"
        structure_type = "None"
        atr_normalized_momentum = 0.73

    class FakeStructureEngine:
        def get_snapshot(self, symbol, tf, cache=None):
            raise AssertionError("must reuse the supplied structure_snapshot, not refetch")

    class FakeBias:
        bias_label = "neutral"
        bias_score = 0.0

    class FakeBiasEngine:
        def get_bias(self, symbol, tf, structure_snapshot=None, cache=None):
            return FakeBias()

    class FakeMomentum:
        score = 0.0004  # legacy raw score, unrelated to atr_normalized_momentum

    class FakeMomentumEngine:
        def get_momentum(self, symbol, tf, cache=None):
            return FakeMomentum()

    class FakeDemandEngine:
        def get_label(self, symbol, tf, cache=None):
            raise AssertionError("unrelated to this test")

    class FakeShiftEngine:
        # Fix #6AK — StyleEngine.get_style_snapshot() now calls the
        # two-phase API (detect_zone_interaction_evidence() +
        # build_zone_interaction_result()) instead of the old single
        # detect_zone_interaction() call; detect_zone_interaction()/
        # detect_shift() are kept below only as harmless leftover API
        # surface, composed from the same two methods, unused by
        # get_style_snapshot() any more.
        def detect_zone_interaction_evidence(self, structure, tf, cache=None):
            return {"interacted": False, "interaction_direction": "Neutral", "zone_type": "neutral", "level": None,
                    "shifted": False, "shift_direction": "Neutral"}

        def build_zone_interaction_result(self, evidence, conviction=None):
            return {"zone_interaction": evidence["interacted"], "zone_interaction_direction": evidence["interaction_direction"],
                    "zone_interaction_color": "#ccc", "shifted": evidence["shifted"], "shift_direction": evidence["shift_direction"],
                    "shift_color": "#ccc"}

        def detect_zone_interaction(self, structure, tf, conviction=None, cache=None):
            evidence = self.detect_zone_interaction_evidence(structure, tf, cache=cache)
            return self.build_zone_interaction_result(evidence, conviction)

        def detect_shift(self, structure, tf, conviction=None, cache=None):
            return self.detect_zone_interaction(structure, tf, conviction=conviction, cache=cache)

        def get_last_shift_change_time(self, symbol, tf):
            return None

    snapshot = get_style_snapshot(
        symbol="TEST", tf="M15", mode="scalping",
        bias_engine=FakeBiasEngine(), momentum_engine=FakeMomentumEngine(),
        demand_engine=FakeDemandEngine(), structure_engine=FakeStructureEngine(),
        shift_engine=FakeShiftEngine(), structure_snapshot=FakeStructure(),
    )
    assert snapshot.atr_normalized_momentum == 0.73
    assert snapshot.momentum == 0.0004  # legacy field: still the raw score, untouched


def test_get_style_snapshot_defaults_to_none_for_minimal_fake_structure():
    """Backward compatibility: a structure object without
    atr_normalized_momentum (e.g. a pre-existing minimal test double) must
    not raise -- defaults to None via getattr()."""
    from core.StyleEngine import get_style_snapshot

    class MinimalFakeStructure:
        context_zone = "neutral"
        structure_type = "None"
        # no atr_normalized_momentum attribute at all

    class FakeBias:
        bias_label = "neutral"
        bias_score = 0.0

    class FakeBiasEngine:
        def get_bias(self, symbol, tf, structure_snapshot=None, cache=None):
            return FakeBias()

    class FakeMomentum:
        score = 0.0

    class FakeMomentumEngine:
        def get_momentum(self, symbol, tf, cache=None):
            return FakeMomentum()

    class FakeShiftEngine:
        # Fix #6AK — see the other FakeShiftEngine above in this file.
        def detect_zone_interaction_evidence(self, structure, tf, cache=None):
            return {"interacted": False, "interaction_direction": "Neutral", "zone_type": "neutral", "level": None,
                    "shifted": False, "shift_direction": "Neutral"}

        def build_zone_interaction_result(self, evidence, conviction=None):
            return {"zone_interaction": evidence["interacted"], "zone_interaction_direction": evidence["interaction_direction"],
                    "zone_interaction_color": "#ccc", "shifted": evidence["shifted"], "shift_direction": evidence["shift_direction"],
                    "shift_color": "#ccc"}

        def detect_zone_interaction(self, structure, tf, conviction=None, cache=None):
            evidence = self.detect_zone_interaction_evidence(structure, tf, cache=cache)
            return self.build_zone_interaction_result(evidence, conviction)

        def get_last_shift_change_time(self, symbol, tf):
            return None

    snapshot = get_style_snapshot(
        symbol="TEST", tf="M15", mode="scalping",
        bias_engine=FakeBiasEngine(), momentum_engine=FakeMomentumEngine(),
        demand_engine=None, structure_engine=None,
        shift_engine=FakeShiftEngine(), structure_snapshot=MinimalFakeStructure(),
    )
    assert snapshot.atr_normalized_momentum is None


# ---------------------------------------------------------------------------
# _normalize_snapshot() wiring (synthetic)
# ---------------------------------------------------------------------------

def test_normalize_snapshot_band_sourced_from_canonical_not_legacy():
    from core.Output.Output import _normalize_snapshot

    class FakeSnap:
        def __init__(self):
            self.momentum = 5.0  # legacy raw score -- would be "strong" under OLD 0.2/0.5 bands
            self.atr_normalized_momentum = 0.3  # canonical -- "weak" under new bands
            self.demand = "neutral"

    result = _normalize_snapshot(FakeSnap())
    assert result["momentum"] == 5.0  # legacy value itself unchanged
    assert result["momentum_band"] == "weak"  # band follows the CANONICAL value, not legacy


def test_normalize_snapshot_band_none_when_canonical_none():
    from core.Output.Output import _normalize_snapshot

    class FakeSnap:
        def __init__(self):
            self.momentum = 1.0
            self.atr_normalized_momentum = None
            self.demand = "neutral"

    result = _normalize_snapshot(FakeSnap())
    assert result["momentum_band"] is None


def test_normalize_snapshot_omits_band_key_when_field_absent():
    """Backward compatibility with any pre-existing fake lacking the new
    field entirely -- must not raise, and simply not set momentum_band."""
    from core.Output.Output import _normalize_snapshot

    snap_dict = {"momentum": 1.0, "demand": "neutral"}
    result = _normalize_snapshot(snap_dict)
    assert "momentum_band" not in result
    assert result["momentum"] == 1.0  # legacy path still ran


# ---------------------------------------------------------------------------
# Existing alignment/conviction/confidence values unchanged
# ---------------------------------------------------------------------------

def test_normalize_snapshot_no_longer_sets_momentum_color_dead_scheme_a_removed():
    """At the time this fix (#6Z) landed, _normalize_snapshot() also set
    snap_dict["momentum_color"] independently of momentum_band (via the
    legacy raw `momentum` and a since-deleted MAX_MOMENTUM constant --
    Fix #6AX) -- that write was always overwritten downstream by
    add_display_percentages() before reaching any consumer (Fix #6AA/#6AC's
    live audits), and Fix #6AD removed it as dead code. Reconfirmed here:
    momentum_band is unaffected by that removal, and _normalize_snapshot()
    no longer produces a momentum_color key at all -- helper.py's
    add_display_percentages() is now the only place that sets it."""
    from core.Output.Output import _normalize_snapshot

    class FakeSnap:
        def __init__(self, atr_norm):
            self.momentum = 0.8
            self.atr_normalized_momentum = atr_norm
            self.demand = "neutral"

    result_a = _normalize_snapshot(FakeSnap(atr_norm=0.1))
    result_b = _normalize_snapshot(FakeSnap(atr_norm=3.0))

    assert "momentum_color" not in result_a
    assert "momentum_color" not in result_b
    # bands still differ correctly, unaffected by the scheme A removal
    assert result_a["momentum_band"] != result_b["momentum_band"]


def test_alignment_signal_momentum_vote_migrated_by_later_fix_6af():
    """At the time this fix (#6Z) landed, alignment_signal.py read only
    .momentum (legacy) and never atr_normalized_momentum -- Fix #6AF later
    migrated the momentum vote itself to canonical atr_normalized_momentum
    (+/-1.0 ATR threshold), per Fix #6AE's audit. This test now documents
    that fact rather than asserting the old (superseded) exclusion; see
    test_alignment_momentum_atr_migration.py for that migration's own
    dedicated tests."""
    from core.Output.alignment_signal import compute_alignment_signal

    snap_with_strong_atr = {"direction": "neutral", "momentum": 0.0004,
                             "shift_confirmed": False, "shift_direction": "Neutral",
                             "atr_normalized_momentum": 1.32}
    snap_without_atr = {"direction": "neutral", "momentum": 0.0004,
                         "shift_confirmed": False, "shift_direction": "Neutral"}

    result_with = compute_alignment_signal({"M15": snap_with_strong_atr}, mode="scalping")
    result_without = compute_alignment_signal({"M15": snap_without_atr}, mode="scalping")

    # A strong (>1.0 ATR) canonical value now DOES change the outcome vs.
    # one that's absent entirely -- the opposite of this test's original
    # (pre-#6AF) assertion.
    assert result_with["total_score"] == 1.0
    assert result_without["total_score"] == 0.0
    assert result_with["total_score"] != result_without["total_score"]


def test_conviction_unaffected_by_atr_normalized_momentum_when_direction_neutral():
    """At the time this fix (#6Z) landed, conviction never read
    atr_normalized_momentum at all, so this held for any direction. Fix
    #6AK later made conviction direction-relative and DOES read
    atr_normalized_momentum (as its momentum term) for bullish/bearish
    snapshots -- see test_direction_relative_conviction.py for that. This
    narrower case still holds for a different reason: a "neutral"
    direction means no directional call exists at all, so every term
    (including momentum) gates to 0 regardless of atr_normalized_momentum's
    value."""
    from core.core_models import StyleSnapshot

    snap_a = StyleSnapshot(symbol="T", timeframe="M15", mode="scalping",
                            direction="neutral", momentum=0.8, bias=1.0,
                            atr_normalized_momentum=0.1)
    snap_b = StyleSnapshot(symbol="T", timeframe="M15", mode="scalping",
                            direction="neutral", momentum=0.8, bias=1.0,
                            atr_normalized_momentum=3.0)
    assert snap_a.conviction == snap_b.conviction == 0.0


# ---------------------------------------------------------------------------
# Live regression: canonical Structure/StyleEngine path, /core/output.
# ---------------------------------------------------------------------------

def test_live_output_momentum_band_matches_canonical_atr_value():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output, _momentum_band

    from mt5.constants import TIMEFRAMES

    symbol = "XAUUSD_i"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], TIMEFRAMES, count=100)

    canonical = {}
    for tf in TIMEFRAMES:
        structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        if structure is not None:
            canonical[tf] = structure.atr_normalized_momentum

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=[symbol],
    )
    assert "error" not in out[symbol]

    checked_any = False
    for style_key in ("scalping", "swing"):
        for tf, snap in out[symbol][style_key].items():
            if not isinstance(snap, dict) or "momentum_band" not in snap:
                continue
            if tf not in canonical:
                continue
            checked_any = True
            expected_band = _momentum_band(canonical[tf])
            assert snap["momentum_band"] == expected_band, f"{style_key}/{tf}"

    assert checked_any


def test_live_style_snapshot_momentum_unchanged_and_atr_normalized_present():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.StyleEngine import get_style_snapshot

    symbol = "XAUUSD_i"
    tf = "M15"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], [tf], count=100)

    structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
    momentum_snapshot = cr.momentum_engine.get_momentum(symbol, tf, cache=cache)

    style = get_style_snapshot(
        symbol, tf, "scalping", cr.bias_engine, cr.momentum_engine, cr.demand_engine,
        cr.structure_engine, cr.shift_engine, cache=cache, structure_snapshot=structure,
    )
    assert style.momentum == momentum_snapshot.score  # legacy field unchanged
    assert style.atr_normalized_momentum == structure.atr_normalized_momentum


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
