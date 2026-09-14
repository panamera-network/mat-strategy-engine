"""Fix #6AU — strategy_momentum_confidence(): canonical, instrument-scale-
independent momentum confidence ingredient for the Strategy layer. Fix
#6AT's audit determined the mapping (linear cap at 2.0 ATR, agreement-
gated against an explicit, non-optional expected_direction) and the exact
accepted direction vocabularies (verified by reading all 7 live plugin
files: {"Bullish", "long"} for bullish, {"Bearish", "short"} for bearish
-- no other vocabulary used anywhere in this repo is accepted).

No plugin calls this helper yet -- this fix only adds it. No Strategy
behavior change, no EntrySuggestion change, normalize_confidence() is
untouched.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_strategy_momentum_confidence_helper.py -v
"""
import pathlib

import pytest

from core.strategy.strategy_models import strategy_momentum_confidence


# ---------------------------------------------------------------------------
# None / zero / unknown-direction -> 0.0
# ---------------------------------------------------------------------------

def test_none_momentum_is_zero():
    assert strategy_momentum_confidence(None, "Bullish") == 0.0
    assert strategy_momentum_confidence(None, "long") == 0.0
    assert strategy_momentum_confidence(None, "Bearish") == 0.0
    assert strategy_momentum_confidence(None, "short") == 0.0


def test_exact_zero_momentum_is_zero_regardless_of_direction():
    assert strategy_momentum_confidence(0.0, "Bullish") == 0.0
    assert strategy_momentum_confidence(0.0, "Bearish") == 0.0
    assert strategy_momentum_confidence(0.0, "long") == 0.0
    assert strategy_momentum_confidence(0.0, "short") == 0.0


@pytest.mark.parametrize("bad_direction", [
    "Neutral", "neutral", "", "bullish", "bearish", "uptrend", "downtrend",
    "buy", "sell", "Long", "Short", "BULLISH", "unknown", "None",
])
def test_unknown_or_neutral_direction_is_zero_even_with_strong_agreeing_magnitude(bad_direction):
    """An unrecognized direction string must be treated exactly like
    Neutral -- zero -- never guessed into the bullish or bearish bucket,
    even when the momentum value would 'agree' with either reading."""
    assert strategy_momentum_confidence(2.5, bad_direction) == 0.0
    assert strategy_momentum_confidence(-2.5, bad_direction) == 0.0


# ---------------------------------------------------------------------------
# Wrong-direction (sign disagreement) -> 0.0
# ---------------------------------------------------------------------------

def test_bullish_direction_with_negative_momentum_is_zero():
    assert strategy_momentum_confidence(-1.5, "Bullish") == 0.0
    assert strategy_momentum_confidence(-1.5, "long") == 0.0


def test_bearish_direction_with_positive_momentum_is_zero():
    assert strategy_momentum_confidence(1.5, "Bearish") == 0.0
    assert strategy_momentum_confidence(1.5, "short") == 0.0


def test_strong_opposite_momentum_never_inflates_confidence():
    """The exact defect Fix #6AT's audit found in the legacy (unsigned)
    field: very strong momentum in the wrong direction must not raise
    confidence at all, not even partially."""
    assert strategy_momentum_confidence(-10.0, "Bullish") == 0.0
    assert strategy_momentum_confidence(10.0, "Bearish") == 0.0


# ---------------------------------------------------------------------------
# Agreeing sign, both accepted vocabularies per direction.
# ---------------------------------------------------------------------------

def test_bullish_forms_both_accepted_identically():
    assert strategy_momentum_confidence(1.0, "Bullish") == strategy_momentum_confidence(1.0, "long")


def test_bearish_forms_both_accepted_identically():
    assert strategy_momentum_confidence(-1.0, "Bearish") == strategy_momentum_confidence(-1.0, "short")


def test_bullish_bearish_symmetry():
    """Equal magnitude, opposite sign, matching direction -- identical
    confidence either way (the mapping must not favor one side)."""
    bullish = strategy_momentum_confidence(1.3, "Bullish")
    bearish = strategy_momentum_confidence(-1.3, "Bearish")
    assert bullish == bearish
    assert bullish > 0.0


# ---------------------------------------------------------------------------
# Boundaries: 0.5 / 1.0 / 2.0 ATR, and the 2.0 ATR cap.
# ---------------------------------------------------------------------------

def test_boundary_0_5_atr():
    assert strategy_momentum_confidence(0.5, "Bullish") == pytest.approx(0.25)


def test_boundary_1_0_atr():
    assert strategy_momentum_confidence(1.0, "Bullish") == pytest.approx(0.5)


def test_boundary_2_0_atr_caps_at_exactly_1():
    assert strategy_momentum_confidence(2.0, "Bullish") == 1.0


def test_beyond_2_0_atr_still_caps_at_1_never_exceeds():
    assert strategy_momentum_confidence(3.7, "Bullish") == 1.0
    assert strategy_momentum_confidence(100.0, "Bullish") == 1.0
    assert strategy_momentum_confidence(-3.7, "Bearish") == 1.0


def test_never_negative_never_above_1_across_a_sweep():
    for x in [-50.0, -5.0, -2.0, -1.0, -0.5, -0.1, 0.1, 0.5, 1.0, 2.0, 5.0, 50.0]:
        for direction in ("Bullish", "Bearish", "long", "short"):
            result = strategy_momentum_confidence(x, direction)
            assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# Cross-instrument independence by construction: the function has no
# instrument/symbol parameter at all, so identical atr_normalized_momentum
# always produces identical confidence regardless of what instrument it
# came from -- this is a structural property, not something that needs a
# live check, but confirmed here explicitly.
# ---------------------------------------------------------------------------

def test_cross_instrument_independence_by_construction():
    import inspect
    sig = inspect.signature(strategy_momentum_confidence)
    assert list(sig.parameters) == ["atr_normalized_momentum", "expected_direction"]

    # Same canonical value "from" a FX-scale reading and a crypto-scale
    # reading (already normalized upstream) must yield the identical result
    # -- there is no instrument-specific branch anywhere in the helper.
    fx_like_value = 0.83   # e.g. EURUSD's atr_normalized_momentum
    crypto_like_value = 0.83  # e.g. BTCUSD's atr_normalized_momentum, same magnitude
    assert strategy_momentum_confidence(fx_like_value, "Bullish") == strategy_momentum_confidence(crypto_like_value, "Bullish")


# ---------------------------------------------------------------------------
# expected_direction is not optional; no plugin calls this yet.
# ---------------------------------------------------------------------------

def test_expected_direction_is_not_optional():
    with pytest.raises(TypeError):
        strategy_momentum_confidence(1.0)


def test_no_live_plugin_calls_the_new_helper_yet():
    """Fix #6AV later migrated the 4 composite plugins (BiasContinuation*/
    DoubleEngulfing/ZoneContinuation) to call this helper -- updated here to
    check only the 3 raw-confidence plugins Fix #6AV deliberately left
    untouched, still pending their own migration."""
    plugin_dir = pathlib.Path("core/strategy")
    plugin_files = [
        "ScalpingBiasCascade.py", "GroupedLastCandleBiasStrategy.py",
        "LastCandleBiasStrategy.py",
    ]
    for name in plugin_files:
        text = (plugin_dir / name).read_text(encoding="utf-8")
        assert "strategy_momentum_confidence" not in text, f"{name} already calls the new helper -- out of this fix's scope"


def test_normalize_confidence_untouched():
    from core.strategy.strategy_models import normalize_confidence
    assert normalize_confidence(5.0) == 0.5
    assert normalize_confidence(0.7) == 0.7
    assert normalize_confidence(None) == 0.0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
