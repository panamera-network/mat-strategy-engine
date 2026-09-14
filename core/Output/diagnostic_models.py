from dataclasses import dataclass
from typing import Any, Optional

# ---------- Config (tune via DI or env) ----------
@dataclass
class ScalpCfg:
    t_strength_seed: float = 1.5            # M1 strength needed to seed
    t_strength_rising_delta: float = 0.2    # Increase considered "rising"
    t_momentum_min: float = 0.3             # Min momentum for validation
    t_bias_abs_min: float = 0.5             # Ignore tiny bias
    swing_support_strength: float = 1.2     # H1 strength to call "supports long"
    # Fix #6AQ — canonical ATR-normalized replacement for the raw-momentum
    # gate above (t_momentum_min). Comparing a fixed raw threshold against
    # StyleSnapshot.momentum (a raw, per-instrument price-unit displacement)
    # is scale-broken across instruments (Fix #6AP's audit: EURUSD/GBPUSD
    # essentially never clear 0.3 regardless of true strength; BTCUSD clears
    # it trivially regardless of true strength). build_scalping.py's and
    # swing_diag.py's momentum_ok check now gate on this value against the
    # canonical atr_normalized_momentum instead. 0.5 is the existing
    # weak/moderate boundary (Fix #6Z) — momentum_ok's original intent was
    # "exclude negligible/noise momentum", not "require strong momentum",
    # so this is the smallest already-established canonical boundary that
    # matches that intent. t_momentum_min itself is left defined and
    # unchanged -- still read (display-only, not for gating) by
    # build_scalping.py's and swing_diag.py's own `thresholds` output.
    # Fix #6BS — the sole live caller of this constant for actual gating,
    # diagnostic_models.py's own orphan enrich_scalping_with_cascade()
    # (dead code, confirmed zero callers by Fix #6BR's audit), was deleted.
    t_momentum_min_atr: float = 0.5


# Shared diagnostic config + timeframe orders — single source of truth,
# imported by Output.py and helper.py so they can't drift apart.
cfg = ScalpCfg(
    t_strength_seed=1.5,
    t_strength_rising_delta=0.2,
    t_momentum_min=0.3,
    t_bias_abs_min=0.5,
    swing_support_strength=1.2,
    t_momentum_min_atr=0.5,
)

SCALPING_ORDER = ["M1", "M5", "M15", "M30"]
SWING_ORDER = ["H1", "H4", "D1", "W1", "MN1"]
BIAS_ORDER = SCALPING_ORDER + SWING_ORDER

# ---------- Helpers for hybrid dict/object access ----------
def get(item: Any, key: str, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)

def label_up(label: Optional[str]) -> bool:
    return (label or "").lower() == "up"

def label_neutral_or_up(label: Optional[str]) -> bool:
    v = (label or "").lower()
    return v in ("neutral", "up")

def flipped_up(prev_label: Optional[str], curr_label: Optional[str]) -> bool:
    prev = (prev_label or "").lower()
    curr = (curr_label or "").lower()
    return prev in ("down", "neutral") and curr == "up"

def normalize_struct_label(lbl: Optional[str]) -> str:
    # Normalize across "Neutral"/"None"/None variants
    if not lbl:
        return "None"
    if lbl.lower() == "neutral":
        return "Neutral"
    return lbl
