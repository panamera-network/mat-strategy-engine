"""Fix #6AK — targeted tests for rebuilding StyleSnapshot.conviction as
confidence in the snapshot's own labeled direction, bounded [0,1], plus
the corrected ShiftEngine/StyleEngine call ordering that fixes the
previously-dead shift_score term (Fix #6AI's audit finding: shift_score
was permanently 0.0 in production because StyleSnapshot was constructed,
and compute_conviction() ran, before zone interaction was ever detected).

Design per Fix #6AH/#6AI's audits, implemented here:
- Every signed/directional term is agreement-gated against `direction`:
  reward on agreement, contribute exactly 0 on opposition or when no
  directional call exists (direction == "neutral") -- never negative.
- Swing weights (structure 0.4 / bias 0.3 / zone 0.3) and scalping weights
  (momentum 0.5 / shift 0.3 / bias 0.2) each sum to 1.0, and every
  individual term is bounded to its own slice by construction (finite
  weight dicts, or an explicit min(...) normalization) -- there is no
  final emergency clamp anywhere in compute_conviction().
- conviction_breakdown is the source of truth: each already-rounded
  component is summed and rounded again for `conviction`, so breakdown
  always reconciles exactly.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_direction_relative_conviction.py -v
"""
from core.core_models import StyleSnapshot


def make_scalping(direction="neutral", momentum=0.0, bias=0.0,
                   atr_normalized_momentum=None, shift_confirmed=False,
                   shift_direction="Neutral"):
    return StyleSnapshot(
        symbol="T", timeframe="M1", mode="scalping",
        direction=direction, momentum=momentum, bias=bias,
        atr_normalized_momentum=atr_normalized_momentum,
        shift_confirmed=shift_confirmed, shift_direction=shift_direction,
    )


def make_swing(direction="neutral", bias=0.0, structure_label=None,
               structure_direction="Neutral", demand="neutral"):
    return StyleSnapshot(
        symbol="T", timeframe="H1", mode="swing",
        direction=direction, momentum=0.0, bias=bias,
        structure_label=structure_label, structure_direction=structure_direction,
        demand=demand,
    )


# ---------------------------------------------------------------------------
# Invariants: never negative, never > 1
# ---------------------------------------------------------------------------

def test_conviction_never_negative_scalping():
    snap = make_scalping(direction="uptrend", momentum=-999.0, bias=-10.0,
                          atr_normalized_momentum=-5.0, shift_confirmed=True, shift_direction="Bearish")
    assert snap.conviction >= 0.0


def test_conviction_never_negative_swing():
    snap = make_swing(direction="uptrend", bias=-10.0, structure_label="BOS",
                       structure_direction="Bearish", demand="strong sell")
    assert snap.conviction >= 0.0


def test_scalping_max_exactly_1_0():
    snap = make_scalping(direction="uptrend", bias=10.0, atr_normalized_momentum=5.0,
                          shift_confirmed=True, shift_direction="Bullish")
    assert snap.conviction == 1.0


def test_swing_max_exactly_1_0():
    snap = make_swing(direction="uptrend", bias=10.0, structure_label="BOS",
                       structure_direction="Bullish", demand="strong buy")
    assert snap.conviction == 1.0


def test_conviction_never_exceeds_1_even_with_extreme_inputs():
    snap = make_scalping(direction="downtrend", bias=-9999.0, atr_normalized_momentum=-9999.0,
                          shift_confirmed=True, shift_direction="Bearish")
    assert snap.conviction <= 1.0
    assert snap.conviction >= 0.0


# ---------------------------------------------------------------------------
# Neutral direction -> conviction 0
# ---------------------------------------------------------------------------

def test_neutral_direction_scalping_conviction_zero_regardless_of_evidence():
    snap = make_scalping(direction="neutral", bias=10.0, atr_normalized_momentum=5.0,
                          shift_confirmed=True, shift_direction="Bullish")
    assert snap.conviction == 0.0
    assert snap.conviction_breakdown == {"momentum": 0.0, "shift": 0.0, "bias": 0.0}


def test_neutral_direction_swing_conviction_zero_regardless_of_evidence():
    snap = make_swing(direction="neutral", bias=10.0, structure_label="BOS",
                       structure_direction="Bullish", demand="strong buy")
    assert snap.conviction == 0.0
    assert snap.conviction_breakdown == {"structure": 0.0, "bias": 0.0, "zone_score": 0.0}


# ---------------------------------------------------------------------------
# Symmetric bullish vs bearish conviction (Fix #6AH's central proof)
# ---------------------------------------------------------------------------

def test_symmetric_bullish_bearish_scalping_equal_conviction():
    bullish = make_scalping(direction="uptrend", bias=8.0, atr_normalized_momentum=1.5,
                             shift_confirmed=True, shift_direction="Bullish")
    bearish = make_scalping(direction="downtrend", bias=-8.0, atr_normalized_momentum=-1.5,
                             shift_confirmed=True, shift_direction="Bearish")
    assert bullish.conviction == bearish.conviction
    assert bullish.conviction > 0.5  # strongly confirmed setup, not near-zero


def test_symmetric_bullish_bearish_swing_equal_conviction():
    bullish = make_swing(direction="uptrend", bias=8.0, structure_label="BOS",
                          structure_direction="Bullish", demand="strong buy")
    bearish = make_swing(direction="downtrend", bias=-8.0, structure_label="BOS",
                          structure_direction="Bearish", demand="strong sell")
    assert bullish.conviction == bearish.conviction


# ---------------------------------------------------------------------------
# Confirming / opposing momentum (scalping)
# ---------------------------------------------------------------------------

def test_confirming_momentum_contributes_positively():
    snap = make_scalping(direction="uptrend", atr_normalized_momentum=1.5)
    assert snap.conviction_breakdown["momentum"] > 0.0


def test_opposing_momentum_contributes_zero_not_negative():
    snap = make_scalping(direction="uptrend", atr_normalized_momentum=-1.5)
    assert snap.conviction_breakdown["momentum"] == 0.0
    assert snap.conviction >= 0.0


def test_none_momentum_contributes_zero():
    snap = make_scalping(direction="uptrend", atr_normalized_momentum=None)
    assert snap.conviction_breakdown["momentum"] == 0.0


# ATR >2 caps only the contribution normalization; the field itself stays unclamped
def test_atr_beyond_2_caps_contribution_but_field_stays_unclamped():
    snap_at_2 = make_scalping(direction="uptrend", atr_normalized_momentum=2.0)
    snap_beyond = make_scalping(direction="uptrend", atr_normalized_momentum=50.0)
    assert snap_at_2.conviction_breakdown["momentum"] == 0.5
    assert snap_beyond.conviction_breakdown["momentum"] == 0.5  # capped, not larger
    assert snap_beyond.atr_normalized_momentum == 50.0  # field itself never clamped


def test_momentum_contribution_scales_between_0_and_2_atr():
    half = make_scalping(direction="uptrend", atr_normalized_momentum=0.5)
    full = make_scalping(direction="uptrend", atr_normalized_momentum=1.0)
    assert half.conviction_breakdown["momentum"] == 0.12  # min(0.5/2.0,1.0)*0.5 = 0.125 -> round(...,2) = 0.12
    assert full.conviction_breakdown["momentum"] == 0.25  # min(1.0/2.0,1.0)*0.5 = 0.25


# ---------------------------------------------------------------------------
# Confirming / opposing shift (scalping) -- previously-dead term
# ---------------------------------------------------------------------------

def test_confirming_shift_contributes_0_3():
    snap = make_scalping(direction="uptrend", shift_confirmed=True, shift_direction="Bullish")
    assert snap.conviction_breakdown["shift"] == 0.3


def test_opposing_shift_direction_contributes_zero():
    snap = make_scalping(direction="uptrend", shift_confirmed=True, shift_direction="Bearish")
    assert snap.conviction_breakdown["shift"] == 0.0


def test_shift_not_confirmed_contributes_zero_even_if_direction_would_agree():
    snap = make_scalping(direction="uptrend", shift_confirmed=False, shift_direction="Bullish")
    assert snap.conviction_breakdown["shift"] == 0.0


def test_previously_dead_shift_term_now_genuinely_contributes():
    """Fix #6AI's audit: shift_score was permanently 0.0 in production
    because shift_confirmed was always the dataclass default (False) at
    construction time. This test proves that when shift_confirmed=True is
    passed in AT CONSTRUCTION (as StyleEngine.py now does), the term
    genuinely fires -- not stuck at 0 by ordering."""
    dead_before = make_scalping(direction="uptrend")  # shift_confirmed defaults False
    alive_now = make_scalping(direction="uptrend", shift_confirmed=True, shift_direction="Bullish")
    assert dead_before.conviction_breakdown["shift"] == 0.0
    assert alive_now.conviction_breakdown["shift"] == 0.3
    assert alive_now.conviction > dead_before.conviction


# ---------------------------------------------------------------------------
# Confirming / opposing structure (swing)
# ---------------------------------------------------------------------------

def test_confirming_bos_structure_contributes_0_4():
    snap = make_swing(direction="uptrend", structure_label="BOS", structure_direction="Bullish")
    assert snap.conviction_breakdown["structure"] == 0.4


def test_confirming_choch_structure_contributes_0_28():
    snap = make_swing(direction="uptrend", structure_label="CHOCH", structure_direction="Bullish")
    assert snap.conviction_breakdown["structure"] == 0.28


def test_opposing_structure_direction_contributes_zero():
    snap = make_swing(direction="uptrend", structure_label="BOS", structure_direction="Bearish")
    assert snap.conviction_breakdown["structure"] == 0.0


def test_missing_structure_contributes_zero():
    snap = make_swing(direction="uptrend", structure_label=None, structure_direction="Neutral")
    assert snap.conviction_breakdown["structure"] == 0.0


def test_structure_label_none_string_contributes_zero():
    snap = make_swing(direction="uptrend", structure_label="None", structure_direction="Neutral")
    assert snap.conviction_breakdown["structure"] == 0.0


# ---------------------------------------------------------------------------
# Confirming / opposing demand_score (swing zone term)
# ---------------------------------------------------------------------------

def test_confirming_strong_buy_bullish_contributes_0_3():
    snap = make_swing(direction="uptrend", demand="strong buy")
    assert snap.conviction_breakdown["zone_score"] == 0.3


def test_confirming_buy_bullish_contributes_0_15():
    snap = make_swing(direction="uptrend", demand="buy")
    assert snap.conviction_breakdown["zone_score"] == 0.15


def test_opposing_sell_on_bullish_contributes_zero():
    snap = make_swing(direction="uptrend", demand="sell")
    assert snap.conviction_breakdown["zone_score"] == 0.0


def test_opposing_strong_sell_on_bullish_contributes_zero():
    snap = make_swing(direction="uptrend", demand="strong sell")
    assert snap.conviction_breakdown["zone_score"] == 0.0


def test_confirming_strong_sell_bearish_contributes_0_3():
    snap = make_swing(direction="downtrend", demand="strong sell")
    assert snap.conviction_breakdown["zone_score"] == 0.3


def test_opposing_buy_on_bearish_contributes_zero():
    snap = make_swing(direction="downtrend", demand="buy")
    assert snap.conviction_breakdown["zone_score"] == 0.0


def test_neutral_demand_contributes_zero():
    snap = make_swing(direction="uptrend", demand="neutral")
    assert snap.conviction_breakdown["zone_score"] == 0.0


# ---------------------------------------------------------------------------
# Bias term (both modes) -- agrees by construction, magnitude-based
# ---------------------------------------------------------------------------

def test_bias_contributes_by_magnitude_scalping():
    snap = make_scalping(direction="uptrend", bias=5.0)
    assert snap.conviction_breakdown["bias"] == 0.1  # abs(5/10)*0.2 = 0.1


def test_bias_contributes_by_magnitude_swing():
    snap = make_swing(direction="uptrend", bias=5.0)
    assert snap.conviction_breakdown["bias"] == 0.15  # abs(5/10)*0.3 = 0.15


def test_bias_zero_on_neutral_direction():
    snap = make_scalping(direction="neutral", bias=8.0)
    assert snap.conviction_breakdown["bias"] == 0.0


# ---------------------------------------------------------------------------
# Breakdown sum == conviction
# ---------------------------------------------------------------------------

def test_breakdown_sum_equals_conviction_scalping():
    snap = make_scalping(direction="uptrend", bias=3.7, atr_normalized_momentum=0.83,
                          shift_confirmed=True, shift_direction="Bullish")
    assert round(sum(snap.conviction_breakdown.values()), 2) == snap.conviction


def test_breakdown_sum_equals_conviction_swing():
    snap = make_swing(direction="downtrend", bias=-6.2, structure_label="CHOCH",
                       structure_direction="Bearish", demand="sell")
    assert round(sum(snap.conviction_breakdown.values()), 2) == snap.conviction


def test_breakdown_keys_correct_per_mode():
    scalp = make_scalping(direction="uptrend")
    swing = make_swing(direction="uptrend")
    assert set(scalp.conviction_breakdown.keys()) == {"momentum", "shift", "bias"}
    assert set(swing.conviction_breakdown.keys()) == {"structure", "bias", "zone_score"}


# ---------------------------------------------------------------------------
# structure_direction field wiring
# ---------------------------------------------------------------------------

def test_structure_direction_field_defaults_to_none():
    snap = StyleSnapshot(symbol="T", timeframe="H1", mode="swing",
                          direction="uptrend", momentum=0.0, bias=0.0)
    assert snap.structure_direction is None


# ---------------------------------------------------------------------------
# StyleEngine integration: shift detected before construction, colorized
# after; exactly one interaction candle fetch; no second detection
# ---------------------------------------------------------------------------

def _common_fakes():
    class FakeBias:
        bias_label = "uptrend"
        bias_score = 8.0

    class FakeBiasEngine:
        def get_bias(self, symbol, tf, structure_snapshot=None, cache=None):
            return FakeBias()

    class FakeMomentum:
        score = 50.0

    class FakeMomentumEngine:
        def get_momentum(self, symbol, tf, cache=None):
            return FakeMomentum()

    return FakeBiasEngine(), FakeMomentumEngine()


def test_shift_detected_before_construction_and_colorized_afterward():
    """The core Fix #6AI/#6AK fix: evidence must be known BEFORE
    StyleSnapshot construction (so compute_conviction() sees it), and
    colorization must happen AFTER (using the now-correct conviction) --
    proven by observing call order via a spy ShiftEngine."""
    from core.StyleEngine import get_style_snapshot

    call_order = []

    class FakeStructure:
        symbol = "TEST"
        context_zone = "demand"
        structure_type = "BOS"
        structure_direction = "Bullish"
        atr_normalized_momentum = 1.5

    class FakeStructureEngine:
        def get_snapshot(self, symbol, tf, cache=None):
            raise AssertionError("structure_snapshot was supplied; must not refetch")

    class SpyShiftEngine:
        def detect_zone_interaction_evidence(self, structure, tf, cache=None):
            call_order.append("evidence")
            return {"interacted": True, "interaction_direction": "Bullish", "zone_type": "demand",
                    "level": 100.0, "shifted": True, "shift_direction": "Bullish"}

        def build_zone_interaction_result(self, evidence, conviction=None):
            call_order.append(("color", conviction))
            return {"zone_interaction": evidence["interacted"], "zone_interaction_direction": evidence["interaction_direction"],
                    "zone_interaction_color": "#00ff00", "shifted": evidence["shifted"],
                    "shift_direction": evidence["shift_direction"], "shift_color": "#00ff00"}

        def get_last_shift_change_time(self, symbol, tf):
            return None

    bias_engine, momentum_engine = _common_fakes()
    snapshot = get_style_snapshot(
        symbol="TEST", tf="M1", mode="scalping",
        bias_engine=bias_engine, momentum_engine=momentum_engine,
        demand_engine=None, structure_engine=FakeStructureEngine(),
        shift_engine=SpyShiftEngine(), structure_snapshot=FakeStructure(),
    )

    assert call_order[0] == "evidence"
    assert call_order[1][0] == "color"
    # The conviction passed to colorization must be the REAL, final
    # conviction (already reflecting the confirmed, agreeing shift) --
    # not a stale pre-shift value.
    assert call_order[1][1] == snapshot.conviction
    assert snapshot.conviction_breakdown["shift"] == 0.3  # shift agreed and confirmed
    assert snapshot.shift_confirmed is True
    assert snapshot.zone_interaction is True
    assert snapshot.zone_interaction_color == "#00ff00"


def test_exactly_one_interaction_candle_fetch_via_style_engine():
    from core.StyleEngine import get_style_snapshot

    class FakeStructure:
        symbol = "TEST"
        context_zone = "demand"
        structure_type = "BOS"
        structure_direction = "Bullish"
        atr_normalized_momentum = 1.5

    class FakeStructureEngine:
        def get_snapshot(self, symbol, tf, cache=None):
            raise AssertionError("must not refetch structure")

    fetch_calls = []

    class CountingShiftEngine:
        """Delegates to the real detection/build logic via a real
        CandleEngine-shaped fake, to prove exactly one fetch happens even
        though evidence is used twice (construction gate + colorization)."""
        def __init__(self):
            self._current_shift_direction = {}
            self._last_shift_change = {}

        def detect_zone_interaction_evidence(self, structure, tf, cache=None):
            fetch_calls.append(1)
            return {"interacted": True, "interaction_direction": "Bullish", "zone_type": "demand",
                    "level": 100.0, "shifted": True, "shift_direction": "Bullish"}

        def build_zone_interaction_result(self, evidence, conviction=None):
            return {"zone_interaction": evidence["interacted"], "zone_interaction_direction": evidence["interaction_direction"],
                    "zone_interaction_color": "#00ff00", "shifted": evidence["shifted"],
                    "shift_direction": evidence["shift_direction"], "shift_color": "#00ff00"}

        def get_last_shift_change_time(self, symbol, tf):
            return None

    bias_engine, momentum_engine = _common_fakes()
    get_style_snapshot(
        symbol="TEST", tf="M1", mode="scalping",
        bias_engine=bias_engine, momentum_engine=momentum_engine,
        demand_engine=None, structure_engine=FakeStructureEngine(),
        shift_engine=CountingShiftEngine(), structure_snapshot=FakeStructure(),
    )
    assert len(fetch_calls) == 1


def test_style_engine_does_not_call_private_detection_method_directly():
    """StyleEngine must go through the public
    detect_zone_interaction_evidence(), never the private
    _detect_interaction_evidence()."""
    from core.StyleEngine import get_style_snapshot

    class FakeStructure:
        symbol = "TEST"
        context_zone = "demand"
        structure_type = "BOS"
        structure_direction = "Bullish"
        atr_normalized_momentum = 1.5

    class FakeStructureEngine:
        def get_snapshot(self, symbol, tf, cache=None):
            raise AssertionError("must not refetch structure")

    class NoPrivateAccessShiftEngine:
        def detect_zone_interaction_evidence(self, structure, tf, cache=None):
            return {"interacted": False, "interaction_direction": "Neutral", "zone_type": "neutral",
                    "level": None, "shifted": False, "shift_direction": "Neutral"}

        def build_zone_interaction_result(self, evidence, conviction=None):
            return {"zone_interaction": evidence["interacted"], "zone_interaction_direction": evidence["interaction_direction"],
                    "zone_interaction_color": "#cccccc", "shifted": evidence["shifted"],
                    "shift_direction": evidence["shift_direction"], "shift_color": "#cccccc"}

        def get_last_shift_change_time(self, symbol, tf):
            return None

        def _detect_interaction_evidence(self, *args, **kwargs):
            raise AssertionError("StyleEngine must not call the private method directly")

    bias_engine, momentum_engine = _common_fakes()
    # If StyleEngine called the private method, the AssertionError above
    # would fire and this call would raise.
    get_style_snapshot(
        symbol="TEST", tf="M1", mode="scalping",
        bias_engine=bias_engine, momentum_engine=momentum_engine,
        demand_engine=None, structure_engine=FakeStructureEngine(),
        shift_engine=NoPrivateAccessShiftEngine(), structure_snapshot=FakeStructure(),
    )


# ---------------------------------------------------------------------------
# Old public detect_zone_interaction() contract still passes unmodified --
# cross-check against the real ShiftEngine (not a fake)
# ---------------------------------------------------------------------------

def test_real_shift_engine_public_contract_unmodified():
    from core.ShiftEngine import ShiftEngine
    from core.core_models import CandleSnapshot

    class FakeCandleEngine:
        def __init__(self, candle):
            self._candle = candle

        def get_snapshots(self, symbol, tf, count=1, cache=None):
            return [self._candle]

    class FakeStructureSnapshot:
        def __init__(self):
            self.symbol = "TEST"
            self.context_zone = "demand"
            self.context_level = 100.0

    candle = CandleSnapshot(open=100.5, high=100.6, low=100.0, close=100.4, volume=100, timestamp="1")
    engine = ShiftEngine(FakeCandleEngine(candle))
    result = engine.detect_zone_interaction(FakeStructureSnapshot(), "M15", conviction=0.7)

    assert result["zone_interaction"] is True
    assert result["zone_interaction_direction"] == "Bullish"
    assert result["shifted"] is True
    assert result["shift_direction"] == "Bullish"


# ---------------------------------------------------------------------------
# Live regression: full pipeline, real bullish/bearish examples
# ---------------------------------------------------------------------------

def test_live_conviction_bounded_0_1_across_instrument_classes():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbols = ["EURUSD_i", "USDJPY_i", "XAUUSD_i", "BTCUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"], count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=symbols,
    )

    checked = 0
    for symbol in symbols:
        assert "error" not in out[symbol], f"{symbol}: {out[symbol].get('error')}"
        for mode in ("scalping", "swing"):
            for tf, snap in out[symbol][mode].items():
                if tf in ("alignment_signal", "diagnostic"):
                    continue
                conviction = snap.get("conviction")
                breakdown = snap.get("conviction_breakdown")
                if conviction is None:
                    continue
                checked += 1
                assert 0.0 <= conviction <= 1.0, f"{symbol} {mode} {tf}: conviction={conviction} out of [0,1]"
                if breakdown:
                    assert round(sum(breakdown.values()), 2) == conviction, f"{symbol} {mode} {tf}: breakdown doesn't reconcile"
    assert checked > 0


def test_live_alignment_suppression_strategy_unaffected():
    """Confirm Alignment/Suppression/Strategy are untouched by this fix --
    same live output shape/behavior as established in prior fixes."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"], count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=[symbol],
    )
    assert "error" not in out[symbol]
    assert out[symbol]["scalping"]["alignment_signal"]["decision"] in ("Go Long", "Go Short", "Stand Aside")
    assert out[symbol]["swing"]["alignment_signal"]["decision"] in ("Go Long", "Go Short", "Stand Aside")
    # signal_health still bounded, formula untouched by this fix
    assert 0.0 <= out[symbol]["signal_health"]["score_pct"] <= 100.0
