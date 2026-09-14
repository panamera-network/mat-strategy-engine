"""Fix #6E — targeted tests proving structure_ok now means a real
confirmed BOS/CHoCH only (never a zone-touch substitute), across the two
live diagnostic builders that had the bad `st in {"BOS","CHOCH"} or
(st=="Neutral" and shift)` pattern:
  - core/Output/build_scalping.py::build_scalping_diagnostic()
  - core/Output/swing_diag.py::enrich_swing_with_diagnostic()

A third builder, core/Output/diagnostic_models.py::enrich_scalping_with_cascade(),
had the same pattern and its own 4 tests here originally, but Fix #6BR's
audit confirmed it was dead code (zero callers anywhere in the repo) whose
regression coverage fully duplicated the build_scalping_diagnostic() tests
below; Fix #6BS deleted the function and those 4 redundant tests.

zone_interaction_ok was added as a new, separately-observable checks key in
build_scalping.py (it computes its score via an explicit named list, so a
new dict key cannot affect it). swing_diag.py's conviction_score is
computed generically over every checks.values(), so a new key there WOULD
silently change that score — audited and deliberately NOT added; zone
interaction stays observable there via the pre-existing shift_ok key
instead.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_structure_ok_zone_interaction_split.py -v
"""
from core.core_models import StyleSnapshot
from core.Output.build_scalping import build_scalping_diagnostic
from core.Output.diagnostic_models import ScalpCfg
from core.Output.swing_diag import enrich_swing_with_diagnostic

CFG = ScalpCfg()


def make_snapshot(tf, structure_label, shift_confirmed, zone_interaction, momentum=1.0):
    return StyleSnapshot(
        symbol="FIX6E_TEST", timeframe=tf, mode="scalping", direction="neutral",
        momentum=momentum, bias=0.0,
        structure_label=structure_label,
        shift_confirmed=shift_confirmed, zone_interaction=zone_interaction,
        demand="neutral",
    )


def make_bias_entry(label="neutral"):
    return {"bias_label": label, "strength_diagnostic": None}


# ---------------------------------------------------------------------------
# build_scalping.py::build_scalping_diagnostic()
# ---------------------------------------------------------------------------

def _run_build_scalping(structure_label, shift_confirmed, zone_interaction, symbol="FIX6E_TEST_BS"):
    scalping_map = {
        tf: make_snapshot(tf, structure_label if tf == "M5" else "None", shift_confirmed if tf == "M5" else False, zone_interaction if tf == "M5" else False)
        for tf in ("M1", "M5", "M15", "M30")
    }
    bias_map = {tf: make_bias_entry() for tf in ("M1", "M5", "M15")}
    result = build_scalping_diagnostic(symbol=symbol, scalping_map=scalping_map, bias_map=bias_map, cfg=CFG)
    return result["diagnostic"]["checks"]


def test_build_scalping_structure_ok_false_for_neutral_with_zone_interaction():
    checks = _run_build_scalping("Neutral", shift_confirmed=True, zone_interaction=True)
    assert checks["structure_ok"] is False


def test_build_scalping_structure_ok_true_for_bos_without_zone_interaction():
    checks = _run_build_scalping("BOS", shift_confirmed=False, zone_interaction=False)
    assert checks["structure_ok"] is True


def test_build_scalping_structure_ok_true_for_choch_without_zone_interaction():
    checks = _run_build_scalping("CHOCH", shift_confirmed=False, zone_interaction=False)
    assert checks["structure_ok"] is True


def test_build_scalping_zone_interaction_ok_independently_observable():
    checks_neutral_touch = _run_build_scalping("Neutral", shift_confirmed=True, zone_interaction=True)
    assert checks_neutral_touch["structure_ok"] is False
    assert checks_neutral_touch["zone_interaction_ok"] is True
    assert checks_neutral_touch["shift_ok"] is True

    checks_bos_no_touch = _run_build_scalping("BOS", shift_confirmed=False, zone_interaction=False)
    assert checks_bos_no_touch["structure_ok"] is True
    assert checks_bos_no_touch["zone_interaction_ok"] is False
    assert checks_bos_no_touch["shift_ok"] is False


# ---------------------------------------------------------------------------
# swing_diag.py::enrich_swing_with_diagnostic()
# ---------------------------------------------------------------------------

def _run_swing_diag(structure_label, shift_confirmed, symbol="FIX6E_TEST_SW"):
    def snap(tf, sl="None", sh=False):
        return {
            "structure_label": sl, "shift_confirmed": sh, "demand": "neutral",
            "suppression": False, "momentum": 1.0, "direction": "Neutral",
        }

    swing_map = {
        "H1": snap("H1"),
        "H4": snap("H4", sl=structure_label, sh=shift_confirmed),
        "D1": snap("D1"),
    }
    bias_map = {tf: make_bias_entry() for tf in ("H1", "H4", "D1")}
    result = enrich_swing_with_diagnostic(symbol=symbol, swing_map=swing_map, bias_map=bias_map, cfg=CFG)
    return result["diagnostic"]["checks"]


def test_swing_diag_structure_ok_false_for_neutral_with_zone_interaction():
    checks = _run_swing_diag("Neutral", shift_confirmed=True)
    assert checks["structure_ok"] is False


def test_swing_diag_structure_ok_true_for_bos_without_zone_interaction():
    checks = _run_swing_diag("BOS", shift_confirmed=False)
    assert checks["structure_ok"] is True


def test_swing_diag_structure_ok_true_for_choch_without_zone_interaction():
    checks = _run_swing_diag("CHOCH", shift_confirmed=False)
    assert checks["structure_ok"] is True


def test_swing_diag_zone_interaction_remains_observable_via_shift_ok():
    """No new key added here (audited — see module docstring); shift_ok
    alone must still correctly reflect zone interaction independent of the
    now-corrected structure_ok."""
    checks_neutral_touch = _run_swing_diag("Neutral", shift_confirmed=True)
    assert checks_neutral_touch["structure_ok"] is False
    assert checks_neutral_touch["shift_ok"] is True

    checks_choch_no_touch = _run_swing_diag("CHOCH", shift_confirmed=False)
    assert checks_choch_no_touch["structure_ok"] is True
    assert checks_choch_no_touch["shift_ok"] is False

    assert "zone_interaction_ok" not in checks_neutral_touch


def test_swing_diag_conviction_score_denominator_unchanged():
    """Guard against ever accidentally adding a new checks key here —
    conviction_score is sum(true)/len(all), so the check-count must stay
    exactly what it was before this fix (11 keys: bias_h1_up, bias_h4_up,
    bias_d1_neutral_or_up, h4_flip_up, h1_strength_ok, h4_strength_rising,
    momentum_ok, structure_ok, shift_ok, demand_supports, suppression)."""
    checks = _run_swing_diag("BOS", shift_confirmed=False)
    assert len(checks) == 11


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
