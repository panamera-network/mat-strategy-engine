"""Fix #6I — targeted tests for BiasEngine.evaluate_bias()'s BOS
continuation gate: full BOS structure score (±8) only when pre_break_trend
actually matches structure_direction (Fix #6H's audit found today's BOS
label is a default/fallback, not evidenced continuation, whenever
pre_break_trend is Neutral). CHoCH behavior is unchanged — always ±10
when valid, regardless of pre_break_trend.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_bias_bos_continuation_gate.py -v
"""
from core.BiasEngine import BiasEngine, STRUCTURE_BIAS_SCORE
from core.core_models import CandleSnapshot


def c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100, timestamp=ts)


class FakeStructure:
    def __init__(self, structure_valid, structure_type, structure_direction, pre_break_trend):
        self.structure_valid = structure_valid
        self.structure_type = structure_type
        self.structure_direction = structure_direction
        self.pre_break_trend = pre_break_trend


def make_engine():
    # candle_engine/strength_engine unused by evaluate_bias() directly.
    return BiasEngine(candle_engine=None, strength_engine=None)


# Candles with a known, computable candle-ratio fallback: 3 up-closes, 2
# down-closes -> bias_score = round((3-2)/5*10, 2) = 2.0 -> "uptrend".
# Distinct from +/-8/+/-10 so a fallback vs. structure-override result is
# unambiguous in assertions below.
FALLBACK_CANDLES_BULLISH_LEANING = [
    c(100, 101, 99, 101, "1"),  # up
    c(101, 102, 100, 102, "2"),  # up
    c(102, 103, 101, 100, "3"),  # down
    c(100, 101, 99, 101, "4"),  # up
    c(101, 102, 100, 99, "5"),  # down
]
EXPECTED_FALLBACK_LABEL = "uptrend"
EXPECTED_FALLBACK_SCORE = 2.0


def test_bullish_choch_remains_plus_ten():
    engine = make_engine()
    structure = FakeStructure(True, "CHOCH", "Bullish", pre_break_trend="Bearish")
    label, score = engine.evaluate_bias(FALLBACK_CANDLES_BULLISH_LEANING, structure_snapshot=structure)
    assert label == "uptrend"
    assert score == STRUCTURE_BIAS_SCORE["CHOCH"] == 10.0


def test_bearish_choch_remains_minus_ten():
    engine = make_engine()
    structure = FakeStructure(True, "CHOCH", "Bearish", pre_break_trend="Bullish")
    label, score = engine.evaluate_bias(FALLBACK_CANDLES_BULLISH_LEANING, structure_snapshot=structure)
    assert label == "downtrend"
    assert score == -STRUCTURE_BIAS_SCORE["CHOCH"] == -10.0


def test_bullish_bos_with_matching_bullish_pretrend_is_plus_eight():
    engine = make_engine()
    structure = FakeStructure(True, "BOS", "Bullish", pre_break_trend="Bullish")
    label, score = engine.evaluate_bias(FALLBACK_CANDLES_BULLISH_LEANING, structure_snapshot=structure)
    assert label == "uptrend"
    assert score == STRUCTURE_BIAS_SCORE["BOS"] == 8.0


def test_bearish_bos_with_matching_bearish_pretrend_is_minus_eight():
    engine = make_engine()
    structure = FakeStructure(True, "BOS", "Bearish", pre_break_trend="Bearish")
    label, score = engine.evaluate_bias(FALLBACK_CANDLES_BULLISH_LEANING, structure_snapshot=structure)
    assert label == "downtrend"
    assert score == -STRUCTURE_BIAS_SCORE["BOS"] == -8.0


def test_bullish_bos_with_neutral_pretrend_uses_candle_fallback():
    engine = make_engine()
    structure = FakeStructure(True, "BOS", "Bullish", pre_break_trend="Neutral")
    label, score = engine.evaluate_bias(FALLBACK_CANDLES_BULLISH_LEANING, structure_snapshot=structure)
    assert score != STRUCTURE_BIAS_SCORE["BOS"]
    assert label == EXPECTED_FALLBACK_LABEL
    assert score == EXPECTED_FALLBACK_SCORE


def test_bearish_bos_with_neutral_pretrend_uses_candle_fallback():
    engine = make_engine()
    structure = FakeStructure(True, "BOS", "Bearish", pre_break_trend="Neutral")
    label, score = engine.evaluate_bias(FALLBACK_CANDLES_BULLISH_LEANING, structure_snapshot=structure)
    assert score != -STRUCTURE_BIAS_SCORE["BOS"]
    assert label == EXPECTED_FALLBACK_LABEL
    assert score == EXPECTED_FALLBACK_SCORE


def test_bos_with_missing_pretrend_falls_back_conservatively():
    """pre_break_trend=None (missing/unresolvable evidence) must not
    invent a score — same fallback as Neutral."""
    engine = make_engine()
    structure = FakeStructure(True, "BOS", "Bullish", pre_break_trend=None)
    label, score = engine.evaluate_bias(FALLBACK_CANDLES_BULLISH_LEANING, structure_snapshot=structure)
    assert score != STRUCTURE_BIAS_SCORE["BOS"]
    assert label == EXPECTED_FALLBACK_LABEL
    assert score == EXPECTED_FALLBACK_SCORE


def test_bos_with_inconsistent_pretrend_falls_back_conservatively():
    """A Bullish BOS with an opposite (Bearish) pre_break_trend should
    never occur per detect_structure_event()'s own logic, but BiasEngine
    must handle it defensively — conservative fallback, no invented score,
    never silently flip to the mismatched direction's score either."""
    engine = make_engine()
    structure = FakeStructure(True, "BOS", "Bullish", pre_break_trend="Bearish")
    label, score = engine.evaluate_bias(FALLBACK_CANDLES_BULLISH_LEANING, structure_snapshot=structure)
    assert score not in (STRUCTURE_BIAS_SCORE["BOS"], -STRUCTURE_BIAS_SCORE["BOS"])
    assert label == EXPECTED_FALLBACK_LABEL
    assert score == EXPECTED_FALLBACK_SCORE


def test_structure_bias_score_constant_unchanged():
    assert STRUCTURE_BIAS_SCORE == {"BOS": 8.0, "CHOCH": 10.0}


def test_no_structure_snapshot_still_uses_fallback_unchanged():
    engine = make_engine()
    label, score = engine.evaluate_bias(FALLBACK_CANDLES_BULLISH_LEANING, structure_snapshot=None)
    assert label == EXPECTED_FALLBACK_LABEL
    assert score == EXPECTED_FALLBACK_SCORE


def test_invalid_structure_still_uses_fallback_unchanged():
    engine = make_engine()
    structure = FakeStructure(False, "BOS", "Bullish", pre_break_trend="Bullish")
    label, score = engine.evaluate_bias(FALLBACK_CANDLES_BULLISH_LEANING, structure_snapshot=structure)
    assert label == EXPECTED_FALLBACK_LABEL
    assert score == EXPECTED_FALLBACK_SCORE


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
