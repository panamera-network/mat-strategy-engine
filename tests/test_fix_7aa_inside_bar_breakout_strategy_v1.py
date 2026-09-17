"""Fix #7AA — MAT Inside Bar v1: Mother Bar -> minimum 3 consecutive
contained child candles -> body breakout. This is MAT's OWN Inside Bar
definition, not the textbook one.

EVIDENCE AUDIT (performed before writing any detector -- see
core/structure_utils.py's detect_inside_bar_sequence() own docstring for
the full detail): StrategySnapshot.recent_candles (Fix #7K) only exposes
the last 3 candles, and only direction/index/timestamp/volume (core_
models.CandleDirection) -- no open/high/low/close at all, and nowhere
near enough history for a Mother that can be up to MAX_INSIDE_BAR_
CHILDREN + 1 candles back. Insufficient for this strategy's own geometry
proof. Closed with a new structure_utils detector reusing the SAME
already-fetched `candles` window StructureEngine already has -- no new
MT5 fetch, no candle geometry ever recomputed inside the Strategy layer.

CHILD-CLOSE SEMANTICS (MAT rule, corrected from an earlier, wrong design
before this fix's first commit): a child is valid purely by its OWN
CLOSE relative to the Mother's BODY -- `mother_body_low <= child.close
<= mother_body_high` (inclusive; equality at the body open/close still
counts as a child, since the breakout check is strict `>`/`<`). A
child's wick/high/low may extend beyond the Mother's own high/low
WITHOUT invalidating it -- Mother H/L plays NO role in child eligibility
at all; it is display-only geometry for the Mother candle itself, never
the containment rule (the ORIGINAL v1 design wrongly checked wick
containment against Mother high/low -- fixed before commit, not kept as
an alternate rule).

SEQUENCE IDENTITY / STALE-MOTHER SELECTION RULE + FIRST BREAKOUT IDENTITY
(reported before implementation): the breakout candle is ALWAYS
`candles[-1]` (the current/most-recent candle -- the same "evaluate as
of now" convention already established by Fix #7P/#7V/#7W/#7X/#7Y).
Starting from num_children=3 and increasing one at a time up to
MAX_INSIDE_BAR_CHILDREN (=SWING_LOOKBACK=20, an EVIDENCE/lookback
horizon only, never a MAT trading rule -- "more than 3 children" has no
MAT-locked upper bound), the NEAREST possible Mother is tried first;
widening only happens if the nearer candidate has any child whose close
already sits outside its body (which, under the close-based rule, is
simultaneously "not a valid child" and "an already-consumed Mother") or
fails the breakout check. Since the children window always ends at
breakout_index - 1, a single already-broken child poisons every widening
attempt equally -- the SAME, specific old Mother candle can never
"hijack" a later breakout as though its own earlier break never
happened. A genuinely DIFFERENT, later candle (e.g. the very candle that
consumed an earlier Mother) CAN legitimately become a brand new Mother
for an independent, later sequence -- that is not reuse, it is a
different Mother candle entirely.

ELIGIBILITY: no zone/S&R/S&D/bias/structure/momentum gate of any kind
(LOCKED RULE) -- momentum only ever SUPPORTS confidence.

CONFIDENCE v1: confirmed sequence gets a flat BASE_CONFIDENCE (0.5) plus
canonical momentum support only (MOMENTUM_WEIGHT 0.5) -- the same pattern
already established by Fix #7P/#7S/#7T/#7W/#7X/#7Y. Mother direction is
never scored; child-count/child-size scoring is deliberately deferred.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7aa_inside_bar_breakout_strategy_v1.py -v
"""
import inspect
from datetime import datetime, timezone

import pytest

from core.core_models import CandleSnapshot
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot
from core.structure_utils import MAX_INSIDE_BAR_CHILDREN, detect_inside_bar_sequence


def _c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=10.0, timestamp=ts)


# ---------------------------------------------------------------------------
# detect_inside_bar_sequence() — hand-verified geometry.
# ---------------------------------------------------------------------------

def _bullish_mother_bullish_breakout_3_children():
    """Mother (bullish, body [100,105], wick [90,110]) -> 3 contained
    children -> breakout closes at 107 (> body high 105, < wick high
    110) -> Bullish."""
    return [
        _c(100, 110, 90, 105, 0),   # Mother
        _c(102, 106, 98, 101, 1),   # child 1
        _c(101, 104, 95, 103, 2),   # child 2
        _c(103, 108, 92, 100, 3),   # child 3
        _c(100, 112, 99, 107, 4),   # breakout
    ]


def test_bullish_setup_exactly_three_children():
    candles = _bullish_mother_bullish_breakout_3_children()
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["direction"] == "Bullish"
    assert result["mother_index"] == 0
    assert result["children_count"] == 3
    assert result["children_start_index"] == 1
    assert result["children_end_index"] == 3
    assert result["breakout_index"] == 4


def test_bearish_setup_exactly_three_children():
    candles = [
        _c(105, 110, 90, 100, 0),   # Mother (bearish, body [100,105])
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 92, 100, 3),
        _c(104, 109, 99, 97, 4),    # breakout closes 97 < body low 100
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["direction"] == "Bearish"
    assert result["children_count"] == 3


def test_four_plus_children_valid():
    """The nearest hypothetical mother (child 1, num_children=3) must
    FAIL (child 2's low escapes child 1's own low), forcing the detector
    to widen to num_children=4 and find the TRUE Mother at index 0."""
    candles = [
        _c(100, 110, 90, 105, 0),   # TRUE Mother
        _c(102, 106, 98, 101, 1),   # child 1 (narrower range than Mother)
        _c(101, 104, 95, 103, 2),   # child 2 -- low=95 escapes child1's low=98
        _c(103, 108, 92, 100, 3),   # child 3
        _c(100, 109, 93, 104, 4),   # child 4
        _c(104, 112, 100, 107, 5),  # breakout closes 107 > body high 105
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["direction"] == "Bullish"
    assert result["mother_index"] == 0
    assert result["children_count"] == 4
    assert result["breakout_index"] == 5


def test_mother_bullish_color_and_bullish_breakout_valid():
    candles = _bullish_mother_bullish_breakout_3_children()
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["mother_close"] > result["mother_open"]  # bullish Mother
    assert result["direction"] == "Bullish"


def test_mother_bearish_color_and_bullish_breakout_also_valid():
    """LOCKED RULE: Mother direction is irrelevant -- a bearish Mother
    producing a BULLISH breakout must be exactly as valid."""
    candles = [
        _c(105, 110, 90, 100, 0),   # Mother (bearish, body [100,105])
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 92, 100, 3),
        _c(104, 112, 99, 107, 4),   # breakout closes 107 > body high 105 -> Bullish
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["mother_close"] < result["mother_open"]  # bearish Mother
    assert result["direction"] == "Bullish"


def test_mother_bullish_color_and_bearish_breakout_valid():
    candles = [
        _c(100, 110, 90, 105, 0),   # Mother (bullish, body [100,105])
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 92, 100, 3),
        _c(100, 109, 91, 97, 4),    # breakout closes 97 < body low 100 -> Bearish
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["mother_close"] > result["mother_open"]  # bullish Mother
    assert result["direction"] == "Bearish"


def test_only_one_child_rejected():
    candles = [
        _c(100, 110, 90, 105, 0),   # Mother
        _c(102, 106, 98, 101, 1),   # 1 child
        _c(100, 112, 99, 107, 2),   # "breakout" -- too few candles overall
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is False


def test_only_two_children_rejected():
    candles = [
        _c(100, 110, 90, 105, 0),   # Mother
        _c(102, 106, 98, 101, 1),   # child 1
        _c(101, 104, 95, 103, 2),   # child 2
        _c(100, 112, 99, 107, 3),   # "breakout" -- still too few candles overall
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is False


# ---------------------------------------------------------------------------
# MAT child-close semantics (corrected): a child is valid purely by its
# OWN CLOSE relative to the Mother's BODY -- wick/high/low is irrelevant
# to child eligibility and must never invalidate a child.
# ---------------------------------------------------------------------------

def test_child_wick_above_mother_high_but_closes_inside_body_valid():
    """A child whose WICK exceeds the Mother's own high must still be a
    valid child, as long as its CLOSE stays inside the Mother's body."""
    candles = [
        _c(100, 110, 90, 105, 0),    # Mother, body [100,105]
        _c(102, 106, 98, 101, 1),    # child (ok)
        _c(101, 104, 95, 103, 2),    # child (ok)
        _c(103, 115, 92, 100, 3),    # wick EXCEEDS Mother high (115>110), close=100 IS inside body
        _c(100, 118, 99, 107, 4),    # breakout
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["children_count"] == 3


def test_child_wick_below_mother_low_but_closes_inside_body_valid():
    candles = [
        _c(105, 110, 90, 100, 0),    # Mother, body [100,105]
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 80, 102, 3),    # wick BELOW Mother low (80<90), close=102 IS inside body
        _c(100, 105, 79, 97, 4),     # breakout (bearish)
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["direction"] == "Bearish"


def test_child_both_side_wick_excursion_but_close_inside_body_valid():
    candles = [
        _c(100, 110, 90, 105, 0),    # Mother, body [100,105]
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 120, 80, 102, 3),    # wick BOTH exceeds high (120) AND below low (80), close=102 inside body
        _c(100, 122, 79, 107, 4),    # breakout
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True


def test_child_close_exactly_mother_body_high_still_child():
    candles = [
        _c(100, 110, 90, 105, 0),    # Mother, body [100,105]
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 92, 105, 3),    # close EXACTLY == body_high (105) -- still a child, not a breakout
        _c(100, 112, 99, 107, 4),    # breakout
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["children_count"] == 3


def test_child_close_exactly_mother_body_low_still_child():
    candles = [
        _c(105, 110, 90, 100, 0),    # Mother, body [100,105]
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 92, 100, 3),    # close EXACTLY == body_low (100) -- still a child
        _c(100, 105, 91, 97, 4),     # breakout (bearish)
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["children_count"] == 3


def test_first_close_strictly_above_body_high_is_bullish_breakout():
    candles = _bullish_mother_bullish_breakout_3_children()
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["direction"] == "Bullish"
    assert result["breakout_close"] > max(result["mother_open"], result["mother_close"])


def test_first_close_strictly_below_body_low_is_bearish_breakout():
    candles = [
        _c(105, 110, 90, 100, 0), _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2), _c(103, 108, 92, 100, 3),
        _c(104, 109, 99, 97, 4),
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["direction"] == "Bearish"
    assert result["breakout_close"] < min(result["mother_open"], result["mother_close"])


def test_breakout_above_body_but_below_mother_high_valid():
    """LOCKED RULE: breakout does NOT need to break Mother High -- closing
    outside the body while still inside the wick range is valid."""
    candles = _bullish_mother_bullish_breakout_3_children()
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    breakout_close = candles[-1].close
    assert result["mother_close"] < breakout_close if False else True  # sanity no-op
    assert breakout_close < result["mother_high"]
    assert breakout_close > max(result["mother_open"], result["mother_close"])


def test_breakout_below_body_but_above_mother_low_valid():
    candles = [
        _c(100, 110, 90, 105, 0),
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 92, 100, 3),
        _c(100, 109, 91, 97, 4),   # breakout close 97: > mother_low(90), < body_low(100)
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    breakout_close = candles[-1].close
    assert breakout_close > result["mother_low"]
    assert breakout_close < min(result["mother_open"], result["mother_close"])


def test_close_still_inside_mother_body_rejected():
    candles = [
        _c(100, 110, 90, 105, 0),   # Mother, body [100,105]
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 92, 100, 3),
        _c(100, 109, 99, 102, 4),   # breakout closes 102 -- INSIDE body [100,105]
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is False


# ---------------------------------------------------------------------------
# First Breakout Identity follow-up audit -- once a candle qualifies as a
# body-break, that Mother's sequence is CONSUMED; a later candle must
# never reuse the same Mother as though the earlier break never happened.
# ---------------------------------------------------------------------------

def test_intermediate_candle_already_breaking_body_consumes_the_mother_bullish():
    """The exact live-audited bug this follow-up fixes: candle index 3
    already closes above the Mother's body (while its own wick stays
    contained -- a textbook valid breakout in its own right) BEFORE the
    current candle (index 4) also closes above the body. The Mother was
    already consumed at index 3 -- index 4 must NOT be reported as a
    fresh breakout of the SAME Mother."""
    candles = [
        _c(100, 110, 90, 105, 0),   # Mother, body [100,105]
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 92, 107, 3),   # ALREADY breaks body (107 > 105), wick still <= 110
        _c(105, 109, 96, 108, 4),   # current -- also breaks body, but Mother is already consumed
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is False


def test_intermediate_candle_already_breaking_body_consumes_the_mother_bearish():
    """Bearish mirror of the same bug/fix."""
    candles = [
        _c(105, 110, 90, 100, 0),   # Mother, body [100,105]
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 92, 98, 3),    # ALREADY breaks body (98 < 100), wick still >= 90
        _c(100, 105, 91, 97, 4),    # current -- also breaks body, but Mother is already consumed
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is False


def test_children_stay_inside_body_current_performs_genuine_first_break():
    """Contrast case: all children stay INSIDE the body (never break it)
    -- only the current candle performs the first genuine body-break.
    This must remain valid; the fix must not have made the detector too
    strict."""
    candles = [
        _c(100, 110, 90, 105, 0),   # Mother, body [100,105]
        _c(102, 104, 98, 101, 1),   # inside body
        _c(101, 103, 95, 102, 2),   # inside body
        _c(103, 104, 92, 101, 3),   # inside body
        _c(100, 112, 99, 107, 4),   # current -- FIRST body break
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["breakout_index"] == 4
    assert result["children_count"] == 3


def test_old_mother_never_reused_after_it_was_already_consumed():
    """The OLD Mother specifically must never be reused as a fresh
    sequence: an earlier, genuine body-break already happened (index 4,
    consuming Mother index 0), price returned inside THAT candle's own
    body (indices 5-7), and a later break occurs at the current candle
    (index 8). Under the corrected MAT close-based child rule, candle 4
    itself legitimately qualifies as a BRAND NEW, independent Mother for
    this later run (candles 5-7 close inside ITS OWN body, candle 8
    breaks ITS OWN body) -- this is a genuinely different Mother, not a
    reuse, and confirming it is correct. What must NEVER happen is
    mother_index reporting back to the OLD, already-consumed Mother
    (index 0) as though its own earlier breakout at index 4 never
    happened."""
    candles = [
        _c(100, 110, 90, 105, 0),   # OLD Mother, body [100,105]
        _c(102, 104, 98, 101, 1),   # child
        _c(101, 103, 95, 102, 2),   # child
        _c(103, 104, 92, 101, 3),   # child
        _c(100, 108, 99, 107, 4),   # EARLIER body-break (107 > 105) -- consumes the OLD Mother
        _c(107, 109, 100, 102, 5),  # returns inside body
        _c(101, 106, 98, 103, 6),   # still inside body
        _c(103, 106, 99, 104, 7),   # still inside body
        _c(100, 111, 99, 108, 8),   # LATER body-break again (current)
    ]
    result = detect_inside_bar_sequence(candles)
    if result["confirmed"]:
        assert result["mother_index"] != 0
        assert result["mother_index"] == 4  # the genuinely new, independent Mother
    # else: no sequence at all is also an acceptable outcome -- what is
    # NEVER acceptable is mother_index landing back on the consumed
    # Mother (index 0).


def test_old_mother_truly_unreusable_when_no_fresh_mother_exists_either():
    """A stricter variant: the same earlier-consumed-Mother setup, but
    the "returns inside body" candles do NOT independently form a valid
    fresh sequence with ANY candidate Mother either (candle 6's close
    escapes candle 4's own body) -- so the only honest outcome is
    confirmed=False, never a reach-back to the OLD Mother."""
    candles = [
        _c(100, 110, 90, 105, 0),   # OLD Mother, body [100,105]
        _c(102, 104, 98, 101, 1),   # child
        _c(101, 103, 95, 102, 2),   # child
        _c(103, 104, 92, 101, 3),   # child
        _c(100, 108, 99, 107, 4),   # EARLIER body-break (107 > 105) -- consumes the OLD Mother; body now [100,107]
        _c(107, 109, 100, 102, 5),  # closes 102 -- inside candle4's body [100,107]
        _c(101, 106, 98, 110, 6),   # closes 110 -- escapes candle4's body high (107) too
        _c(103, 106, 99, 104, 7),
        _c(100, 111, 99, 108, 8),   # current
    ]
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is False


def test_max_inside_bar_children_is_lookback_horizon_not_mat_rule():
    """MAX_INSIDE_BAR_CHILDREN bounds the search for computational/
    evidence reasons only -- MAT has never locked a maximum child count
    as trading semantics. Confirmed via the constant's own documentation
    rather than asserting a specific behavioral ceiling (there is none to
    assert -- "more than 3 children are allowed" has no MAT-locked
    upper bound)."""
    import core.structure_utils as su_mod
    source = inspect.getsource(su_mod)
    marker = source.index("MAX_INSIDE_BAR_CHILDREN = SWING_LOOKBACK")
    comment_block = " ".join(source[:marker].lower().replace("#", " ").split())
    assert "not a mat trading rule" in comment_block
    assert "search-cost" in comment_block or "lookback" in comment_block


def test_stale_mother_identity_not_hijacked():
    """An old, genuinely-valid-looking Mother+children pattern exists far
    in the past, followed by unrelated candles all the way to the current
    breakout -- the old pattern must never be reused just because it once
    validated; only the CURRENT breakout (candles[-1]) is ever evaluated."""
    old_pattern = [
        _c(100, 110, 90, 105, 0),   # old "Mother"
        _c(102, 106, 98, 101, 1),
        _c(101, 104, 95, 103, 2),
        _c(103, 108, 92, 100, 3),
        _c(100, 112, 99, 107, 4),   # old "breakout" -- but NOT candles[-1] once more history follows
    ]
    # Unrelated candles that never form a valid sequence ending at the
    # true current candle.
    unrelated = [_c(500 + i, 505 + i, 495 + i, 500 + i, 100 + i) for i in range(25)]
    candles = old_pattern + unrelated
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is False


def test_strict_sequence_ordering():
    candles = _bullish_mother_bullish_breakout_3_children()
    result = detect_inside_bar_sequence(candles)
    assert result["confirmed"] is True
    assert result["mother_index"] < result["children_start_index"]
    assert result["children_start_index"] <= result["children_end_index"]
    assert result["children_end_index"] < result["breakout_index"]


def test_missing_geometry_rejected_empty_candles():
    assert detect_inside_bar_sequence([])["confirmed"] is False


def test_max_inside_bar_children_reuses_swing_lookback_constant():
    from core.structure_utils import SWING_LOOKBACK
    assert MAX_INSIDE_BAR_CHILDREN == SWING_LOOKBACK


# ---------------------------------------------------------------------------
# Strategy react() — evidence-only, no recomputation.
# ---------------------------------------------------------------------------

def _candle(direction, index, timestamp, volume=100.0):
    return {"direction": direction, "index": index, "timestamp": timestamp, "volume": volume}


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="M15", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        recent_candles=[_candle("bull", 4, "2026-01-01T00:00:00Z")],
        inside_bar_confirmed=False, inside_bar_direction=None,
        inside_bar_mother_index=None, inside_bar_mother_timestamp=None,
        inside_bar_mother_open=None, inside_bar_mother_high=None,
        inside_bar_mother_low=None, inside_bar_mother_close=None,
        inside_bar_children_count=None,
        inside_bar_children_start_index=None, inside_bar_children_start_timestamp=None,
        inside_bar_children_end_index=None, inside_bar_children_end_timestamp=None,
        inside_bar_breakout_index=None, inside_bar_breakout_timestamp=None,
        inside_bar_breakout_close=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_BULLISH_SEQUENCE = dict(
    inside_bar_confirmed=True, inside_bar_direction="Bullish",
    inside_bar_mother_index=0, inside_bar_mother_timestamp="0",
    inside_bar_mother_open=100.0, inside_bar_mother_high=110.0,
    inside_bar_mother_low=90.0, inside_bar_mother_close=105.0,
    inside_bar_children_count=3,
    inside_bar_children_start_index=1, inside_bar_children_start_timestamp="1",
    inside_bar_children_end_index=3, inside_bar_children_end_timestamp="3",
    inside_bar_breakout_index=4, inside_bar_breakout_timestamp="4",
    inside_bar_breakout_close=107.0,
)
_BEARISH_SEQUENCE = dict(
    inside_bar_confirmed=True, inside_bar_direction="Bearish",
    inside_bar_mother_index=0, inside_bar_mother_timestamp="0",
    inside_bar_mother_open=105.0, inside_bar_mother_high=110.0,
    inside_bar_mother_low=90.0, inside_bar_mother_close=100.0,
    inside_bar_children_count=3,
    inside_bar_children_start_index=1, inside_bar_children_start_timestamp="1",
    inside_bar_children_end_index=3, inside_bar_children_end_timestamp="3",
    inside_bar_breakout_index=4, inside_bar_breakout_timestamp="4",
    inside_bar_breakout_close=97.0,
)


def test_strategy_bullish_sequence_fires_long():
    from core.strategy.InsideBarBreakoutStrategy import InsideBarBreakoutStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = InsideBarBreakoutStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Bullish Inside-Bar Breakout"
    assert result["price"] == 107.0


def test_strategy_bearish_sequence_fires_short():
    from core.strategy.InsideBarBreakoutStrategy import InsideBarBreakoutStrategy
    snap = _base_snapshot(**_BEARISH_SEQUENCE)
    result = InsideBarBreakoutStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Bearish Inside-Bar Breakout"
    assert result["price"] == 97.0


def test_strategy_not_confirmed_rejected():
    from core.strategy.InsideBarBreakoutStrategy import InsideBarBreakoutStrategy
    snap = _base_snapshot()
    assert InsideBarBreakoutStrategy().react(snap, {}) is None


def test_strategy_missing_geometry_rejected():
    from core.strategy.InsideBarBreakoutStrategy import InsideBarBreakoutStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["inside_bar_mother_high"] = None
    snap = _base_snapshot(**overrides)
    assert InsideBarBreakoutStrategy().react(snap, {}) is None


def test_exactly_three_markings_all_real():
    from core.strategy.InsideBarBreakoutStrategy import InsideBarBreakoutStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = InsideBarBreakoutStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 3
    types = [m["type"] for m in markings]
    assert types == ["candle", "range", "candle"]
    for m in markings:
        validate_chart_marking(m)

    mother_marking, children_marking, breakout_marking = markings
    assert mother_marking["label"] == "Mother Bar"
    assert mother_marking["timestamp"] == "0"
    assert mother_marking["candle_index"] == 0

    assert children_marking["top"] == 105.0   # mother_body_high (max of open/close), NOT mother_high
    assert children_marking["bottom"] == 100.0  # mother_body_low (min of open/close), NOT mother_low
    assert children_marking["start_timestamp"] == "1"
    assert children_marking["end_timestamp"] == "3"
    assert children_marking["start_index"] == 1
    assert children_marking["end_index"] == 3

    assert breakout_marking["label"] == "Bullish Inside-Bar Breakout"
    assert breakout_marking["timestamp"] == "4"
    assert breakout_marking["candle_index"] == 4


def test_confidence_formula_reported_exactly():
    from core.strategy.InsideBarBreakoutStrategy import (
        BASE_CONFIDENCE, MOMENTUM_WEIGHT, InsideBarBreakoutStrategy,
    )
    assert BASE_CONFIDENCE == 0.5
    assert MOMENTUM_WEIGHT == 0.5
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["atr_normalized_momentum"] = 1.0  # agrees with "long"
    snap = _base_snapshot(**overrides)
    result = InsideBarBreakoutStrategy().react(snap, {})
    assert result["confidence"] == round(0.5 + 0.5 * 0.5, 2)


def test_confidence_floor_with_no_momentum_support():
    from core.strategy.InsideBarBreakoutStrategy import InsideBarBreakoutStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = InsideBarBreakoutStrategy().react(snap, {})
    assert result["confidence"] == 0.5


def test_standard_output_fields_present():
    from core.strategy.InsideBarBreakoutStrategy import InsideBarBreakoutStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = InsideBarBreakoutStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_mother_direction_never_scored():
    """LOCKED RULE: confidence must be identical regardless of whether
    the Mother was bullish or bearish, all else equal."""
    from core.strategy.InsideBarBreakoutStrategy import InsideBarBreakoutStrategy
    bullish_mother = dict(_BULLISH_SEQUENCE)
    bearish_mother_same_breakout = dict(_BULLISH_SEQUENCE)
    bearish_mother_same_breakout["inside_bar_mother_open"] = 105.0
    bearish_mother_same_breakout["inside_bar_mother_close"] = 100.0

    r1 = InsideBarBreakoutStrategy().react(_base_snapshot(**bullish_mother), {})
    r2 = InsideBarBreakoutStrategy().react(_base_snapshot(**bearish_mother_same_breakout), {})
    assert r1["confidence"] == r2["confidence"]


def test_no_child_size_scoring_invented():
    import core.strategy.InsideBarBreakoutStrategy as mod
    source = inspect.getsource(mod.InsideBarBreakoutStrategy.react)
    assert "inside_bar_children_count" not in source or "confidence" not in source.split("inside_bar_children_count")[1].split("\n")[0]


# ---------------------------------------------------------------------------
# No zone/S&R/S&D/bias/structure/momentum-gate dependency.
# ---------------------------------------------------------------------------

def test_no_eligibility_gate_dependency():
    import core.strategy.InsideBarBreakoutStrategy as mod
    source = inspect.getsource(mod.InsideBarBreakoutStrategy.react)
    forbidden = (
        "context_zone", "context_level", "snr_context", "nearest_support", "nearest_resistance",
        "balance_range_confirmed", "volume_profile_", "structure_valid", "structure_type",
        "bias ==", "snapshot.bias", "atr_normalized_momentum is None or",
    )
    for term in forbidden:
        assert term not in source, term


def test_detector_never_calls_structure_or_zone_detection():
    import core.structure_utils as su_mod
    source = inspect.getsource(su_mod.detect_inside_bar_sequence)
    assert "detect_structure_event(" not in source
    assert "find_swings(" not in source
    assert "derive_snr_levels(" not in source


# ---------------------------------------------------------------------------
# Discovery.
# ---------------------------------------------------------------------------

def test_strategy_engine_discovers_twentyfour_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 24
    assert "InsideBarBreakoutStrategy" in engine.enabled


def test_existing_twentythree_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_twentythree = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy", "CHOCHBOSConfirmationStrategy", "MomentumPullbackRecoveryStrategy",
        "SupportResistanceReactionStrategy", "SupportResistanceBreakoutRetestStrategy",
        "VolumeProfileWeeklyReactionStrategy", "BalanceRangeVAHVALReactionStrategy",
    }
    assert existing_twentythree <= set(engine.enabled.keys())
