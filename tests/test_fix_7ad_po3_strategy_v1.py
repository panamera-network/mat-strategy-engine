"""Fix #7AD — MAT PO3 (Power of Three) v1: Balance candidate ->
Manipulation -> Reclaim -> Distribution Confirmation, per MAT's own
locked rules (confirmed via Fix #7AD's own rule-audit report before
implementation).

ARCHITECTURAL LAW (audited and followed): PO3 consumes the SAME
canonical core.BalanceRangeEngine.detect_balance_range() calculation --
no second accumulation/balance detector, no PO3-specific range geometry.
core/PO3Engine.py replays that exact function across historical prefixes
of the SAME already-fetched `candles` window (no new MT5 fetch) to
identify the currently-active PO3 candidate. It lives OUTSIDE
core/structure_utils.py specifically to avoid a genuine circular import
(demand_engine.py already imports FROM structure_utils.py, so
structure_utils.py cannot import compute_atr/detect_balance_range back
from demand_engine.py/BalanceRangeEngine.py without a cycle) -- see
core/PO3Engine.py's own module docstring for the full detail.

LOCKED MAT RULES:
  Manipulation (STRICT): Bullish hypothesis close < range_low; Bearish
    hypothesis close > range_high. The FIRST outside close owns the
    manipulation identity; consecutive same-side candles are one
    excursion, not new manipulations.
  Reclaim (INCLUSIVE): range_low <= close <= range_high. No midpoint/
    equilibrium requirement. A same-candle jump straight to the opposite
    side without ever satisfying this inclusive reclaim first does NOT
    count as reclaim nor as Distribution.
  Distribution (STRICT, only from "reclaimed"): Bullish close >
    range_high; Bearish close < range_low. A close beyond the ORIGINAL
    manipulation-side boundary instead (same strict test as Manipulation
    itself) = "failed".
  NOT gated on: BOS, CHoCH, FVG, displacement, wick size,
    sustained-closes count, ATR magnitude, session/kill-zone timing. No
    SNR/breakout-retest tolerance reused -- exact canonical
    range_high/range_low only.
  LIFECYCLE: one Balance Range produces at most one PO3; confirmed/
    failed is terminal (consumed); a newer canonical Balance Range
    supersedes an unfinished (non-terminal) candidate outright; no
    arbitrary bar-count expiry; a consumed/superseded range can never be
    resurrected by later unrelated movement.
  STAGES: none | candidate | manipulation | reclaimed | confirmed |
    failed. hypothesis_direction is set once Manipulation begins (a
    HYPOTHESIS); direction is populated ONLY when stage == "confirmed".
    A Strategy may fire ONLY when the current/latest candle IS the
    Distribution confirmation event (checked via the existing Fix #7K
    `recent_candles` evidence, not a new field).

CONFIDENCE v1: confirmed sequence gets a flat BASE_CONFIDENCE (0.5) plus
canonical momentum support only (MOMENTUM_WEIGHT 0.5) -- the same
pattern already established by Fix #7P/.../#7AB/#7AC.

SEQUENCE-SELECTION RULE (reported explicitly, per this fix's own
requirement): candle indices are replayed in chronological order; the
active PO3 candidate is always the most recently confirmed Balance Range
that has not yet reached a terminal stage, or -- once terminal --
remains untouched until a still-newer Balance Range confirms.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7ad_po3_strategy_v1.py -v
"""
import inspect
from datetime import datetime, timezone

from core.core_models import CandleSnapshot
from core.PO3Engine import detect_po3_sequence
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot


def _c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=10.0, timestamp=ts)


def _flat_block(mid, half_width, count, start_ts=0):
    """A `count`-candle block where every candle has the SAME wick both
    sides (mid +/- half_width) and open/close pinned at mid -- constant
    width, constant true range, so ATR and the compression bound line up
    predictably and every candle touches both boundaries trivially. 20
    candles keeps the ATR(14) window, once later manipulation/reclaim/
    distribution candles are appended, dominated by this block's own
    consistent scale rather than contaminated by a short prefix average."""
    return [_c(mid, mid + half_width, mid - half_width, mid, start_ts + i) for i in range(count)]


# range_high=100.5, range_low=99.5, indices 0..19.
BLOCK_A = _flat_block(100.0, 0.5, 20, 0)


def _run(candles_after):
    return detect_po3_sequence(BLOCK_A + candles_after)


# ---------------------------------------------------------------------------
# Both directions, full sequence.
# ---------------------------------------------------------------------------

def test_valid_bullish_po3_full_sequence():
    manip = _c(99.4, 99.5, 98.0, 98.3, 20)
    reclaim = _c(98.3, 100.0, 98.2, 99.9, 21)
    dist = _c(99.9, 101.5, 99.8, 101.2, 22)
    result = _run([manip, reclaim, dist])
    assert result["stage"] == "confirmed"
    assert result["direction"] == "Bullish"
    assert result["hypothesis_direction"] == "Bullish"
    assert result["manipulation_index"] == 20
    assert result["reclaim_index"] == 21
    assert result["distribution_index"] == 22
    assert result["range_high"] == 100.5
    assert result["range_low"] == 99.5


def test_valid_bearish_po3_full_sequence():
    manip = _c(100.6, 102.0, 100.5, 101.7, 20)
    reclaim = _c(101.7, 101.8, 100.0, 100.1, 21)
    dist = _c(100.1, 100.2, 98.5, 98.8, 22)
    result = _run([manip, reclaim, dist])
    assert result["stage"] == "confirmed"
    assert result["direction"] == "Bearish"
    assert result["hypothesis_direction"] == "Bearish"
    assert result["manipulation_index"] == 20
    assert result["reclaim_index"] == 21
    assert result["distribution_index"] == 22


# ---------------------------------------------------------------------------
# Multi-candle manipulation excursion -- identity stays at the FIRST
# outside close.
# ---------------------------------------------------------------------------

def test_multi_candle_manipulation_excursion_identity():
    manip1 = _c(99.4, 99.5, 98.5, 98.9, 20)
    manip2 = _c(98.9, 99.0, 98.0, 98.3, 21)  # same side continues -- NOT a new manipulation
    reclaim = _c(98.3, 100.0, 98.2, 99.9, 22)
    dist = _c(99.9, 101.5, 99.8, 101.2, 23)
    result = _run([manip1, manip2, reclaim, dist])
    assert result["stage"] == "confirmed"
    assert result["manipulation_index"] == 20  # the FIRST excursion candle, not manip2
    assert result["manipulation_close"] == 98.9
    assert result["reclaim_index"] == 22
    assert result["distribution_index"] == 23


# ---------------------------------------------------------------------------
# Required reclaim -- a same-candle jump straight to the opposite side
# without ever reclaiming first must NOT confirm distribution.
# ---------------------------------------------------------------------------

def test_required_reclaim_no_premature_distribution():
    manip = _c(99.4, 99.5, 98.0, 98.3, 20)
    jump = _c(98.3, 101.5, 98.2, 101.2, 21)  # closes beyond range_high WITHOUT reclaiming first
    result = _run([manip, jump])
    assert result["stage"] == "manipulation"
    assert result["distribution_index"] is None


# ---------------------------------------------------------------------------
# Same-side post-reclaim failure.
# ---------------------------------------------------------------------------

def test_same_side_post_reclaim_failure():
    manip = _c(99.4, 99.5, 98.0, 98.3, 20)
    reclaim = _c(98.3, 100.0, 98.2, 99.9, 21)
    fail = _c(99.9, 100.0, 97.5, 97.8, 22)  # closes below range_low AGAIN (original manipulation side)
    result = _run([manip, reclaim, fail])
    assert result["stage"] == "failed"
    assert result["direction"] is None
    assert result["hypothesis_direction"] == "Bullish"  # preserved for transparency
    assert result["distribution_index"] is None


def test_same_side_post_reclaim_failure_bearish():
    manip = _c(100.6, 102.0, 100.5, 101.7, 20)
    reclaim = _c(101.7, 101.8, 100.0, 100.1, 21)
    fail = _c(100.1, 102.5, 100.0, 102.2, 22)  # closes above range_high AGAIN
    result = _run([manip, reclaim, fail])
    assert result["stage"] == "failed"
    assert result["direction"] is None


# ---------------------------------------------------------------------------
# Exact boundary equality.
# ---------------------------------------------------------------------------

def test_manipulation_strict_boundary_equality_rejected():
    touch = _c(99.6, 99.7, 99.5, 99.5, 20)  # closes EXACTLY at range_low
    result = _run([touch])
    assert result["stage"] == "candidate"  # equality does NOT trigger manipulation


def test_reclaim_inclusive_boundary_equality_at_range_low():
    manip = _c(99.4, 99.5, 98.0, 98.3, 20)
    reclaim = _c(98.3, 99.6, 98.2, 99.5, 21)  # closes EXACTLY at range_low
    result = _run([manip, reclaim])
    assert result["stage"] == "reclaimed"


def test_reclaim_inclusive_boundary_equality_at_range_high():
    manip = _c(99.4, 99.5, 98.0, 98.3, 20)
    reclaim = _c(98.3, 100.5, 98.2, 100.5, 21)  # closes EXACTLY at range_high
    result = _run([manip, reclaim])
    assert result["stage"] == "reclaimed"


def test_distribution_strict_boundary_equality_rejected():
    manip = _c(99.4, 99.5, 98.0, 98.3, 20)
    reclaim = _c(98.3, 100.0, 98.2, 99.9, 21)
    dist_eq = _c(99.9, 100.5, 99.8, 100.5, 22)  # closes EXACTLY at range_high
    result = _run([manip, reclaim, dist_eq])
    assert result["stage"] == "reclaimed"  # equality does NOT confirm distribution


def test_failure_strict_boundary_equality_does_not_fail():
    manip = _c(99.4, 99.5, 98.0, 98.3, 20)
    reclaim = _c(98.3, 100.0, 98.2, 99.9, 21)
    fail_eq = _c(99.9, 100.0, 99.5, 99.5, 22)  # closes EXACTLY at range_low
    result = _run([manip, reclaim, fail_eq])
    assert result["stage"] == "reclaimed"  # equality does NOT fail either (inclusive, stays reclaimed)


# ---------------------------------------------------------------------------
# Lifecycle / stale identity.
# ---------------------------------------------------------------------------

def test_newer_range_supersedes_unfinished_candidate():
    """A genuine, later, differently-scaled Balance Range confirming
    while the old candidate is still mid-manipulation (unfinished) must
    supersede it outright -- the old manipulation identity is discarded,
    not carried forward."""
    manip = _c(99.4, 99.5, 90.0, 91.0, 20)  # large displacement, unfinished candidate
    block_b = _flat_block(91.0, 0.3, 20, 21)  # a NEW tight range at the post-displacement level
    result = detect_po3_sequence(BLOCK_A + [manip] + block_b)
    assert result["stage"] == "candidate"
    assert result["range_low"] == 90.7
    assert result["range_high"] == 91.3
    assert result["manipulation_index"] is None  # old manipulation evidence discarded


def test_one_range_one_po3_consumption_and_stale_hijack_prevention():
    """Once confirmed, the range is consumed -- later, unrelated candles
    (even one that coincidentally dips back below the ORIGINAL range_low)
    must never be reinterpreted as new evidence against the already-
    consumed range."""
    manip = _c(99.4, 99.5, 98.0, 98.3, 20)
    reclaim = _c(98.3, 100.0, 98.2, 99.9, 21)
    dist = _c(99.9, 101.5, 99.8, 101.2, 22)
    drift = [
        _c(101.2, 102.5, 101.1, 102.3, 23),
        _c(102.3, 103.5, 102.2, 103.3, 24),
        _c(103.3, 104.5, 97.0, 97.5, 25),  # dips below the ORIGINAL range_low (99.5) -- must be ignored
    ]
    result = _run([manip, reclaim, dist] + drift)
    assert result["stage"] == "confirmed"
    assert result["distribution_index"] == 22  # unchanged -- the original confirmation
    assert result["direction"] == "Bullish"


def test_too_few_candles_rejected():
    result = detect_po3_sequence(BLOCK_A[:3])
    assert result["stage"] == "none"


def test_empty_candles_rejected():
    assert detect_po3_sequence([])["stage"] == "none"


def test_no_active_range_stays_none():
    """A trending, never-compressed sequence never confirms a Balance
    Range at all -- stage must stay "none", not silently default to
    "candidate" with no real range identity."""
    trending = [_c(100.0 + i, 101.0 + i, 99.5 + i, 100.8 + i, i) for i in range(10)]
    result = detect_po3_sequence(trending)
    assert result["stage"] == "none"
    assert result["range_high"] is None


# ---------------------------------------------------------------------------
# Strategy react().
# ---------------------------------------------------------------------------

def _candle(direction, index, timestamp, volume=100.0):
    return {"direction": direction, "index": index, "timestamp": timestamp, "volume": volume}


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="M15", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        recent_candles=[_candle("bull", 22, "22")],
        po3_stage="none", po3_hypothesis_direction=None, po3_direction=None,
        po3_range_start_index=None, po3_range_start_timestamp=None,
        po3_range_end_index=None, po3_range_end_timestamp=None,
        po3_range_high=None, po3_range_low=None,
        po3_manipulation_index=None, po3_manipulation_timestamp=None,
        po3_manipulation_open=None, po3_manipulation_high=None, po3_manipulation_low=None, po3_manipulation_close=None,
        po3_reclaim_index=None, po3_reclaim_timestamp=None,
        po3_reclaim_open=None, po3_reclaim_high=None, po3_reclaim_low=None, po3_reclaim_close=None,
        po3_distribution_index=None, po3_distribution_timestamp=None,
        po3_distribution_open=None, po3_distribution_high=None, po3_distribution_low=None, po3_distribution_close=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_CONFIRMED_BULLISH = dict(
    po3_stage="confirmed", po3_hypothesis_direction="Bullish", po3_direction="Bullish",
    po3_range_start_index=0, po3_range_start_timestamp="0",
    po3_range_end_index=19, po3_range_end_timestamp="19",
    po3_range_high=100.5, po3_range_low=99.5,
    po3_manipulation_index=20, po3_manipulation_timestamp="20",
    po3_manipulation_open=99.4, po3_manipulation_high=99.5, po3_manipulation_low=98.0, po3_manipulation_close=98.3,
    po3_reclaim_index=21, po3_reclaim_timestamp="21",
    po3_reclaim_open=98.3, po3_reclaim_high=100.0, po3_reclaim_low=98.2, po3_reclaim_close=99.9,
    po3_distribution_index=22, po3_distribution_timestamp="22",
    po3_distribution_open=99.9, po3_distribution_high=101.5, po3_distribution_low=99.8, po3_distribution_close=101.2,
    recent_candles=[_candle("bull", 22, "22")],  # current candle IS the distribution candle
)
_CONFIRMED_BEARISH = dict(
    po3_stage="confirmed", po3_hypothesis_direction="Bearish", po3_direction="Bearish",
    po3_range_start_index=0, po3_range_start_timestamp="0",
    po3_range_end_index=19, po3_range_end_timestamp="19",
    po3_range_high=100.5, po3_range_low=99.5,
    po3_manipulation_index=20, po3_manipulation_timestamp="20",
    po3_manipulation_open=100.6, po3_manipulation_high=102.0, po3_manipulation_low=100.5, po3_manipulation_close=101.7,
    po3_reclaim_index=21, po3_reclaim_timestamp="21",
    po3_reclaim_open=101.7, po3_reclaim_high=101.8, po3_reclaim_low=100.0, po3_reclaim_close=100.1,
    po3_distribution_index=22, po3_distribution_timestamp="22",
    po3_distribution_open=100.1, po3_distribution_high=100.2, po3_distribution_low=98.5, po3_distribution_close=98.8,
    recent_candles=[_candle("bear", 22, "22")],
)


def test_strategy_fires_bullish_confirmed_and_fresh():
    from core.strategy.PO3Strategy import PO3Strategy
    snap = _base_snapshot(**_CONFIRMED_BULLISH)
    result = PO3Strategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["price"] == 101.2


def test_strategy_fires_bearish_confirmed_and_fresh():
    from core.strategy.PO3Strategy import PO3Strategy
    snap = _base_snapshot(**_CONFIRMED_BEARISH)
    result = PO3Strategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["price"] == 98.8


def test_strategy_candidate_stage_rejected():
    from core.strategy.PO3Strategy import PO3Strategy
    snap = _base_snapshot(po3_stage="candidate")
    assert PO3Strategy().react(snap, {}) is None


def test_strategy_manipulation_stage_rejected():
    from core.strategy.PO3Strategy import PO3Strategy
    snap = _base_snapshot(po3_stage="manipulation", po3_hypothesis_direction="Bullish")
    assert PO3Strategy().react(snap, {}) is None


def test_strategy_reclaimed_stage_rejected():
    from core.strategy.PO3Strategy import PO3Strategy
    snap = _base_snapshot(po3_stage="reclaimed", po3_hypothesis_direction="Bullish")
    assert PO3Strategy().react(snap, {}) is None


def test_strategy_failed_stage_rejected():
    from core.strategy.PO3Strategy import PO3Strategy
    snap = _base_snapshot(po3_stage="failed", po3_hypothesis_direction="Bullish")
    assert PO3Strategy().react(snap, {}) is None


def test_strategy_stale_distribution_no_repeated_signal():
    """The confirmed PO3's own distribution happened at index 22, but the
    current/latest candle (per recent_candles) is now index 25 -- the
    Strategy must NOT fire on a stale confirmation, and must NOT
    repeatedly fire on every subsequent evaluation after the one true
    firing candle has passed."""
    from core.strategy.PO3Strategy import PO3Strategy
    overrides = dict(_CONFIRMED_BULLISH)
    overrides["recent_candles"] = [_candle("bull", 25, "25")]  # current candle is now 25, not 22
    snap = _base_snapshot(**overrides)
    assert PO3Strategy().react(snap, {}) is None


def test_strategy_missing_geometry_rejected():
    from core.strategy.PO3Strategy import PO3Strategy
    overrides = dict(_CONFIRMED_BULLISH)
    overrides["po3_range_high"] = None
    snap = _base_snapshot(**overrides)
    assert PO3Strategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Chart markings -- exactly 4, all real.
# ---------------------------------------------------------------------------

def test_exactly_four_markings_all_real():
    from core.strategy.PO3Strategy import PO3Strategy
    snap = _base_snapshot(**_CONFIRMED_BULLISH)
    result = PO3Strategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 4
    assert [m["type"] for m in markings] == ["range", "candle", "candle", "candle"]
    for m in markings:
        assert m["direction"] == "long"
        validate_chart_marking(m)

    range_marking, manipulation_marking, reclaim_marking, distribution_marking = markings
    assert range_marking["start_index"] == 0
    assert range_marking["end_index"] == 19
    assert range_marking["top"] == 100.5
    assert range_marking["bottom"] == 99.5
    assert manipulation_marking["candle_index"] == 20
    assert reclaim_marking["candle_index"] == 21
    assert distribution_marking["candle_index"] == 22


def test_marking_identity_sourced_from_detector_not_recomputed():
    """Feed the REAL detector's own output through -- markings' index/
    timestamp must be byte-identical, proving no recalculation in the
    Strategy layer."""
    from core.strategy.PO3Strategy import PO3Strategy

    manip = _c(99.4, 99.5, 98.0, 98.3, 20)
    reclaim = _c(98.3, 100.0, 98.2, 99.9, 21)
    dist = _c(99.9, 101.5, 99.8, 101.2, 22)
    detector_result = _run([manip, reclaim, dist])
    assert detector_result["stage"] == "confirmed"

    snap = _base_snapshot(
        po3_stage=detector_result["stage"],
        po3_hypothesis_direction=detector_result["hypothesis_direction"],
        po3_direction=detector_result["direction"],
        po3_range_start_index=detector_result["range_start_index"],
        po3_range_start_timestamp=detector_result["range_start_timestamp"],
        po3_range_end_index=detector_result["range_end_index"],
        po3_range_end_timestamp=detector_result["range_end_timestamp"],
        po3_range_high=detector_result["range_high"],
        po3_range_low=detector_result["range_low"],
        po3_manipulation_index=detector_result["manipulation_index"],
        po3_manipulation_timestamp=detector_result["manipulation_timestamp"],
        po3_manipulation_open=detector_result["manipulation_open"],
        po3_manipulation_high=detector_result["manipulation_high"],
        po3_manipulation_low=detector_result["manipulation_low"],
        po3_manipulation_close=detector_result["manipulation_close"],
        po3_reclaim_index=detector_result["reclaim_index"],
        po3_reclaim_timestamp=detector_result["reclaim_timestamp"],
        po3_reclaim_open=detector_result["reclaim_open"],
        po3_reclaim_high=detector_result["reclaim_high"],
        po3_reclaim_low=detector_result["reclaim_low"],
        po3_reclaim_close=detector_result["reclaim_close"],
        po3_distribution_index=detector_result["distribution_index"],
        po3_distribution_timestamp=detector_result["distribution_timestamp"],
        po3_distribution_open=detector_result["distribution_open"],
        po3_distribution_high=detector_result["distribution_high"],
        po3_distribution_low=detector_result["distribution_low"],
        po3_distribution_close=detector_result["distribution_close"],
        recent_candles=[_candle("bull", detector_result["distribution_index"], "22")],
    )
    result = PO3Strategy().react(snap, {})
    assert result is not None
    range_marking, manipulation_marking, reclaim_marking, distribution_marking = result["chart_markings"]
    assert range_marking["start_index"] == detector_result["range_start_index"]
    assert range_marking["end_index"] == detector_result["range_end_index"]
    assert manipulation_marking["candle_index"] == detector_result["manipulation_index"]
    assert reclaim_marking["candle_index"] == detector_result["reclaim_index"]
    assert distribution_marking["candle_index"] == detector_result["distribution_index"]


def test_rejected_setup_emits_no_markings_and_no_signal():
    from core.strategy.PO3Strategy import PO3Strategy
    snap = _base_snapshot()  # po3_stage="none"
    assert PO3Strategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Confidence formula.
# ---------------------------------------------------------------------------

def test_confidence_formula_reported_exactly():
    from core.strategy.PO3Strategy import BASE_CONFIDENCE, MOMENTUM_WEIGHT, PO3Strategy
    assert BASE_CONFIDENCE == 0.5
    assert MOMENTUM_WEIGHT == 0.5
    overrides = dict(_CONFIRMED_BULLISH)
    overrides["atr_normalized_momentum"] = 1.0  # agrees with "long"
    snap = _base_snapshot(**overrides)
    result = PO3Strategy().react(snap, {})
    assert result["confidence"] == round(0.5 + 0.5 * 0.5, 2)


def test_confidence_floor_with_no_momentum_support():
    from core.strategy.PO3Strategy import PO3Strategy
    snap = _base_snapshot(**_CONFIRMED_BULLISH)
    result = PO3Strategy().react(snap, {})
    assert result["confidence"] == 0.5


def test_standard_output_fields_present():
    from core.strategy.PO3Strategy import PO3Strategy
    snap = _base_snapshot(**_CONFIRMED_BULLISH)
    result = PO3Strategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


# ---------------------------------------------------------------------------
# Absence of forbidden gates.
# ---------------------------------------------------------------------------

def test_no_eligibility_gate_dependency():
    import core.strategy.PO3Strategy as mod
    source = inspect.getsource(mod.PO3Strategy.react)
    forbidden = (
        "context_zone", "context_level", "snr_context", "nearest_support", "nearest_resistance",
        "structure_valid", "structure_type", "bias ==", "snapshot.bias",
        "choch_confirmed", "snr_flip_confirmed", "fvg", "displacement",
    )
    for term in forbidden:
        assert term not in source, term


def test_detector_never_calls_structure_or_trend_detection():
    import core.PO3Engine as mod
    source = inspect.getsource(mod.detect_po3_sequence)
    assert "detect_structure_event(" not in source
    assert "find_swings(" not in source
    assert "detect_trend(" not in source


def test_detector_no_bos_choch_fvg_wick_atr_session_gate():
    """No BOS/CHoCH/FVG/displacement/wick-size/sustained-closes/ATR-
    magnitude/session/kill-zone gate anywhere -- confirmed by CODE BODY
    absence (the module docstring legitimately discusses these ruled-out
    concepts in prose; scope to statements after each function's own
    docstring to avoid the self-referential trap that hit Fix
    #7W/#7Y/#7AA/#7AB/#7AC)."""
    import ast

    import core.PO3Engine as mod

    source = inspect.getsource(mod.detect_po3_sequence)
    tree = ast.parse(source)
    func_node = tree.body[0]
    body_without_docstring = func_node.body[1:]
    code_only = ast.unparse(ast.Module(body=body_without_docstring, type_ignores=[]))

    forbidden = (
        "detect_structure_event", "choch", "fvg", "displacement", "wick",
        "session", "kill_zone", "sustained", "atr_normalized_momentum",
        "tolerance", "0.25", "0.0003",
    )
    for term in forbidden:
        assert term not in code_only.lower(), term


def test_no_snr_breakout_retest_tolerance_reused():
    """PO3 must use the EXACT canonical range_high/range_low -- no
    SNR/breakout-retest wick-overlap tolerance band added."""
    import core.PO3Engine as mod
    source = inspect.getsource(mod)
    assert "_find_current_leg_origin" not in source
    assert "detect_snr_breakout_retest" not in source
    assert "detect_breakout_retest" not in source


# ---------------------------------------------------------------------------
# Discovery.
# ---------------------------------------------------------------------------

def test_strategy_engine_discovers_twentyseven_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 27
    assert "PO3Strategy" in engine.enabled


def test_existing_twentysix_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_twentysix = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy", "CHOCHBOSConfirmationStrategy", "MomentumPullbackRecoveryStrategy",
        "SupportResistanceReactionStrategy", "SupportResistanceBreakoutRetestStrategy",
        "VolumeProfileWeeklyReactionStrategy", "BalanceRangeVAHVALReactionStrategy",
        "InsideBarBreakoutStrategy", "ThreeInsideStrategy", "ThreeSoldiersCrowsStrategy",
    }
    assert existing_twentysix <= set(engine.enabled.keys())
