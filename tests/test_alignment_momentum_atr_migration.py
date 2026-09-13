"""Fix #6AF — targeted tests for migrating Alignment's momentum vote to
canonical atr_normalized_momentum (Fix #6AE's audit conclusion: +/-1.0 ATR,
the same "strong" threshold already locked by Fix #6Z's bands).

Scope: ONLY the momentum contributor in compute_alignment_signal() migrates.
Bias direction vote (+/-1), TF weights, max_possible, the +/-3 decision
threshold, confidence_pct's formula, and the (already-removed, Fix #6F/#6G)
absence of a zone/structure third vote are all untouched -- tests below
explicitly confirm several of these. conviction/Suppression/Strategy are
untouched by this fix (not exercised by this file at all).

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_alignment_momentum_atr_migration.py -v
"""
from core.Output.alignment_signal import compute_alignment_signal


class FakeSnap:
    """Minimal stand-in for a StyleSnapshot, attribute-access shaped."""
    def __init__(self, direction=None, momentum=None, atr_normalized_momentum=None,
                 zone_interaction=False, zone_interaction_direction="Neutral", shift_confirmed=False):
        self.direction = direction
        self.momentum = momentum
        self.atr_normalized_momentum = atr_normalized_momentum
        self.zone_interaction = zone_interaction
        self.zone_interaction_direction = zone_interaction_direction
        self.shift_confirmed = shift_confirmed


def _m1_only(**kwargs):
    """Isolate a single M1 (weight=1.0, scalping) snapshot so breakdown["M1"]
    reads exactly (direction_vote + momentum_vote) * 1.0 -- the other three
    scalping TFs are absent (contribute 0) and can't cross the +/-3 decision
    threshold on their own, keeping the assertion purely about the vote
    value itself."""
    return {"M1": FakeSnap(**kwargs)}


# ---------------------------------------------------------------------------
# Exact boundary tests (direction=None so breakdown["M1"] is momentum-only)
# ---------------------------------------------------------------------------

def test_plus_0_99_atr_is_zero_vote():
    out = compute_alignment_signal(_m1_only(atr_normalized_momentum=0.99), mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


def test_plus_1_00_atr_is_zero_vote():
    out = compute_alignment_signal(_m1_only(atr_normalized_momentum=1.00), mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


def test_plus_1_01_atr_is_plus_one_vote():
    out = compute_alignment_signal(_m1_only(atr_normalized_momentum=1.01), mode="scalping")
    assert out["breakdown"]["M1"] == 1.0


def test_minus_0_99_atr_is_zero_vote():
    out = compute_alignment_signal(_m1_only(atr_normalized_momentum=-0.99), mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


def test_minus_1_00_atr_is_zero_vote():
    out = compute_alignment_signal(_m1_only(atr_normalized_momentum=-1.00), mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


def test_minus_1_01_atr_is_minus_one_vote():
    out = compute_alignment_signal(_m1_only(atr_normalized_momentum=-1.01), mode="scalping")
    assert out["breakdown"]["M1"] == -1.0


# ---------------------------------------------------------------------------
# None handling
# ---------------------------------------------------------------------------

def test_none_atr_momentum_casts_no_vote():
    out = compute_alignment_signal(_m1_only(atr_normalized_momentum=None, momentum=999.0), mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


def test_missing_atr_momentum_attribute_casts_no_vote():
    class BareSnap:
        def __init__(self):
            self.direction = None
            self.momentum = 999.0
            # no atr_normalized_momentum attribute at all -- pre-Fix-#6Z fake
    out = compute_alignment_signal({"M1": BareSnap()}, mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


# ---------------------------------------------------------------------------
# Legacy raw momentum ignored even if huge
# ---------------------------------------------------------------------------

def test_legacy_momentum_ignored_even_if_huge():
    # A crypto-scale legacy value that would have fired instantly under the
    # old +/-0.3 raw-price-scale rule must not affect the vote any more.
    out = compute_alignment_signal(_m1_only(momentum=165.84, atr_normalized_momentum=0.5), mode="scalping")
    assert out["breakdown"]["M1"] == 0.0  # 0.5 ATR is below the new 1.0 threshold


def test_legacy_momentum_huge_and_negative_ignored():
    out = compute_alignment_signal(_m1_only(momentum=-9328.57, atr_normalized_momentum=0.3), mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


# ---------------------------------------------------------------------------
# Standard FX can now contribute when canonical momentum is strong
# ---------------------------------------------------------------------------

def test_standard_fx_scale_legacy_momentum_now_contributes_via_canonical():
    # Fix #6AE's audit: standard FX's legacy momentum (~0.0001-0.001) never
    # crossed the old +/-0.3 threshold -- 0.0% activation. A tiny legacy
    # value paired with a strong canonical ATR reading must now vote.
    out = compute_alignment_signal(_m1_only(momentum=0.0003, atr_normalized_momentum=1.8), mode="scalping")
    assert out["breakdown"]["M1"] == 1.0

    out_neg = compute_alignment_signal(_m1_only(momentum=-0.0002, atr_normalized_momentum=-1.4), mode="scalping")
    assert out_neg["breakdown"]["M1"] == -1.0


# ---------------------------------------------------------------------------
# Metals/crypto no longer auto-vote merely because nominal price is large
# ---------------------------------------------------------------------------

def test_crypto_scale_legacy_momentum_no_longer_auto_votes():
    # Fix #6AE's audit: metals/crypto's legacy momentum fired on 86-94% of
    # readings purely from absolute price scale, regardless of real
    # relative strength. A huge legacy value with a genuinely weak
    # canonical ATR reading must NOT vote any more.
    out = compute_alignment_signal(_m1_only(momentum=53.46, atr_normalized_momentum=0.15), mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


def test_metals_scale_legacy_momentum_no_longer_auto_votes():
    out = compute_alignment_signal(_m1_only(momentum=17050.5, atr_normalized_momentum=-0.4), mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


# ---------------------------------------------------------------------------
# Bias direction vote unchanged
# ---------------------------------------------------------------------------

def test_bullish_direction_alone_still_plus_one():
    out = compute_alignment_signal(_m1_only(direction="bullish", atr_normalized_momentum=None), mode="scalping")
    assert out["breakdown"]["M1"] == 1.0


def test_bearish_direction_alone_still_minus_one():
    out = compute_alignment_signal(_m1_only(direction="bearish", atr_normalized_momentum=None), mode="scalping")
    assert out["breakdown"]["M1"] == -1.0


def test_uptrend_downtrend_labels_still_recognized():
    out_up = compute_alignment_signal(_m1_only(direction="uptrend", atr_normalized_momentum=None), mode="scalping")
    assert out_up["breakdown"]["M1"] == 1.0
    out_down = compute_alignment_signal(_m1_only(direction="downtrend", atr_normalized_momentum=None), mode="scalping")
    assert out_down["breakdown"]["M1"] == -1.0


def test_direction_and_momentum_combine_as_before():
    out = compute_alignment_signal(_m1_only(direction="bullish", atr_normalized_momentum=1.5), mode="scalping")
    assert out["breakdown"]["M1"] == 2.0  # +1 direction + 1 momentum, weight 1.0

    out_opposed = compute_alignment_signal(_m1_only(direction="bullish", atr_normalized_momentum=-1.5), mode="scalping")
    assert out_opposed["breakdown"]["M1"] == 0.0  # +1 direction, -1 momentum


# ---------------------------------------------------------------------------
# Object and dict snapshot paths consistent
# ---------------------------------------------------------------------------

def test_object_and_dict_paths_give_identical_results():
    obj_snap = {"M1": FakeSnap(direction="bullish", momentum=999.0, atr_normalized_momentum=1.2)}
    dict_snap = {"M1": {"direction": "bullish", "momentum": 999.0, "atr_normalized_momentum": 1.2}}

    out_obj = compute_alignment_signal(obj_snap, mode="scalping")
    out_dict = compute_alignment_signal(dict_snap, mode="scalping")

    assert out_obj["breakdown"]["M1"] == out_dict["breakdown"]["M1"] == 2.0
    assert out_obj["decision"] == out_dict["decision"]
    assert out_obj["total_score"] == out_dict["total_score"]


def test_dict_path_none_atr_momentum_no_vote():
    out = compute_alignment_signal({"M1": {"direction": None, "atr_normalized_momentum": None, "momentum": 500.0}}, mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


def test_dict_path_missing_atr_momentum_key_no_vote():
    out = compute_alignment_signal({"M1": {"direction": None, "momentum": 500.0}}, mode="scalping")
    assert out["breakdown"]["M1"] == 0.0


# ---------------------------------------------------------------------------
# Weights / max_possible / +/-3 decision threshold / confidence formula
# unchanged
# ---------------------------------------------------------------------------

def test_swing_weights_and_max_possible_unchanged():
    # All 5 swing TFs at max momentum+direction agreement (+2 each),
    # weights 1.0/1.5/2.0/2.5/3.0 -- total_score = 2*(1+1.5+2+2.5+3) = 20,
    # max_possible = 2*(1+1.5+2+2.5+3) = 20 -- confidence 100%.
    snaps = {tf: FakeSnap(direction="bullish", atr_normalized_momentum=2.0)
             for tf in ("H1", "H4", "D1", "W1", "MN1")}
    out = compute_alignment_signal(snaps, mode="swing")
    assert out["total_score"] == 20.0
    assert out["confidence_pct"] == 100.0
    assert out["decision"] == "Go Long"


def test_decision_threshold_plus_minus_3_unchanged():
    # Two scalping TFs at full agreement (+2 each, weight 1.0) = total 4 >= 3
    # -> Go Long. One TF alone (+2) = total 2 < 3 -> Stand Aside. Confirms
    # the +/-3 threshold itself, not touched by this fix.
    one_tf = {"M1": FakeSnap(direction="bullish", atr_normalized_momentum=2.0)}
    out_one = compute_alignment_signal(one_tf, mode="scalping")
    assert out_one["total_score"] == 2.0
    assert out_one["decision"] == "Stand Aside"

    two_tf = {
        "M1": FakeSnap(direction="bullish", atr_normalized_momentum=2.0),
        "M5": FakeSnap(direction="bullish", atr_normalized_momentum=2.0),
    }
    out_two = compute_alignment_signal(two_tf, mode="scalping")
    assert out_two["total_score"] == 4.0
    assert out_two["decision"] == "Go Long"


def test_confidence_formula_unchanged():
    # confidence_pct = |total_score| / max_possible * 100, still.
    snaps = {"M1": FakeSnap(direction="bullish", atr_normalized_momentum=2.0)}  # score 2, weight 1.0
    out = compute_alignment_signal(snaps, mode="scalping")
    max_possible = sum(abs(w) * 2 for w in {"M1": 1.0, "M5": 1.0, "M15": 1.0, "M30": 1.0}.values())
    expected_pct = round(abs(2.0) / max_possible * 100, 1)
    assert out["confidence_pct"] == expected_pct


# ---------------------------------------------------------------------------
# No structure/zone third vote reintroduced
# ---------------------------------------------------------------------------

def test_zone_interaction_fields_do_not_vote():
    snaps = {
        "M1": FakeSnap(direction=None, atr_normalized_momentum=None,
                       zone_interaction=True, zone_interaction_direction="Bullish", shift_confirmed=True)
    }
    out = compute_alignment_signal(snaps, mode="scalping")
    assert out["breakdown"]["M1"] == 0.0  # zone fields present and "bullish" but must not vote
    assert out["total_score"] == 0.0


# ---------------------------------------------------------------------------
# Live comparison: old vs new decision flips, documented
# ---------------------------------------------------------------------------

def test_live_old_vs_new_alignment_decision_comparison_documented():
    """Recompute both the legacy (raw momentum, +/-0.3) and canonical
    (atr_normalized_momentum, +/-1.0) alignment decisions from the same
    live StyleSnapshot objects, and print/assert the comparison -- this is
    the "live comparison old vs new decision flips documented" requirement.
    Per Fix #6AE's audit, flips are EXPECTED (the legacy formula was scale-
    broken), so this test documents rather than forbids them."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.StyleEngine import get_style_snapshot
    from mt5.constants import TIMEFRAMES, SYMBOLS

    SCALPING_ORDER = ["M1", "M5", "M15", "M30"]
    SWING_ORDER = ["H1", "H4", "D1", "W1", "MN1"]
    SCALPING_WEIGHTS = {tf: 1.0 for tf in SCALPING_ORDER}
    SWING_WEIGHTS = {"H1": 1.0, "H4": 1.5, "D1": 2.0, "W1": 2.5, "MN1": 3.0}

    # Fix #6AE's audit found ~20.8% of (symbol, mode) decisions flip between
    # the legacy and canonical momentum vote at the 1.0 ATR threshold -- use
    # the full symbol universe (not a handful) so this test actually
    # documents real flip evidence rather than risking a zero-flip sample.
    symbols = SYMBOLS
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, TIMEFRAMES, count=100)

    def direction_vote(d):
        if d in ("uptrend", "bullish"):
            return 1
        if d in ("downtrend", "bearish"):
            return -1
        return 0

    def legacy_vote(m):
        if m is None:
            return 0
        if m > 0.3:
            return 1
        if m < -0.3:
            return -1
        return 0

    def canonical_vote(a):
        if a is None:
            return 0
        if a > 1.0:
            return 1
        if a < -1.0:
            return -1
        return 0

    def decide(style_map, tf_order, weights, vote_fn):
        total = 0
        for tf in tf_order:
            snap = style_map.get(tf)
            if not snap:
                continue
            score = direction_vote(snap.direction) + vote_fn(snap)
            total += score * weights[tf]
        if total >= 3:
            return "Go Long"
        if total <= -3:
            return "Go Short"
        return "Stand Aside"

    comparisons = []
    for symbol in symbols:
        style_map = {}
        for tf in TIMEFRAMES:
            mode = "scalping" if tf in SCALPING_ORDER else "swing"
            snap = get_style_snapshot(
                symbol, tf, mode, cr.bias_engine, cr.momentum_engine, cr.demand_engine,
                cr.structure_engine, cr.shift_engine, cache=cache,
            )
            style_map[tf] = snap

        for mode, tf_order, weights in (("scalping", SCALPING_ORDER, SCALPING_WEIGHTS), ("swing", SWING_ORDER, SWING_WEIGHTS)):
            legacy_decision = decide(style_map, tf_order, weights, lambda s: legacy_vote(s.momentum))
            canonical_decision = decide(style_map, tf_order, weights, lambda s: canonical_vote(s.atr_normalized_momentum))

            # Cross-check: the ACTUAL migrated function must match our
            # manual canonical recomputation exactly.
            actual = compute_alignment_signal({tf: style_map[tf] for tf in tf_order}, mode=mode)
            assert actual["decision"] == canonical_decision, (
                f"{symbol} {mode}: compute_alignment_signal()={actual['decision']} "
                f"but manual canonical recomputation={canonical_decision}"
            )

            comparisons.append((symbol, mode, legacy_decision, canonical_decision, legacy_decision != canonical_decision))

    flips = [c for c in comparisons if c[4]]
    for symbol, mode, legacy_d, canon_d, flipped in comparisons:
        marker = "FLIP" if flipped else "same"
        print(f"{symbol:10s} {mode:9s} legacy={legacy_d:12s} canonical={canon_d:12s} [{marker}]")
    print(f"Total: {len(comparisons)}, flips: {len(flips)} ({100*len(flips)/len(comparisons):.1f}%)")

    assert len(comparisons) == len(symbols) * 2
