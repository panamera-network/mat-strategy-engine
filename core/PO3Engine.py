"""Fix #7AD — MAT PO3 (Power of Three) v1: Balance candidate -> Manipulation
-> Reclaim -> Distribution Confirmation.

ARCHITECTURAL LAW (per this fix's own instruction, and Fix #7AD's own
rule-audit report): PO3 must consume the SAME canonical Balance Range
`core.BalanceRangeEngine.detect_balance_range()` already computes -- no
second accumulation/balance detector, no PO3-specific range geometry.
This module lives OUTSIDE `core/structure_utils.py` specifically because
that module's own docstring states it has "no dependency on other core/
engines" (an actual, not merely stylistic, constraint: `demand_engine.py`
already imports `SWING_WINDOW` FROM `structure_utils.py`, so
`structure_utils.py` importing `detect_balance_range`/`compute_atr` back
FROM `BalanceRangeEngine`/`demand_engine` would be a genuine circular
import). This module follows the SAME pattern as `BalanceRangeEngine.py`/
`VolumeProfileEngine.py`/`ManualRangeVolumeProfile.py`: a standalone
engine module imported directly by `StructureEngine.py`, not a
`structure_utils.py` primitive.

EVIDENCE-REUSE AUDIT (Fix #7AD's own rule-audit report, confirmed before
this implementation): reuses `detect_balance_range()` and `compute_atr()`
completely UNCHANGED -- same functions, same formula, same thresholds.
"Replay" (calling `detect_balance_range()` on historical PREFIXES of the
same already-fetched `candles` window, exactly as StructureEngine.py's
own existing `historical_candles = candles[:-1]` pattern already does for
its single "as of now" Balance Range evidence, just generalized to every
possible cut point instead of only the most recent one) is how a
Balance Range that formed at ANY point in the already-fetched window can
be identified WITHOUT a second formula and WITHOUT any new MT5 fetch --
every prefix `candles[:i+1]` is data already in memory.

WHY A REPLAY SCAN IS NECESSARY (unlike Fix #7AA/#7AB/#7AC's fixed
3-candle window): those patterns are always exactly 3 candles evaluated
"as of now" (candles[-1]), so staleness could never arise structurally.
PO3 cannot use a fixed window -- Manipulation and Distribution can occur
an UNBOUNDED number of candles after a Balance Range confirms. This
module has no persistent state across calls (StructureEngine.get_
snapshot() is stateless, given only the current candles window each
time), so the ENTIRE Accumulation -> Manipulation -> Reclaim ->
Distribution lifecycle must be re-derived from scratch on every call by
replaying forward through the whole already-fetched window -- there is
no other way to honor the lifecycle rules below without persisted state.

LOCKED MAT RULES (Fix #7AD's own instruction, all thresholds either
reused unchanged from `BalanceRangeEngine` or pure boundary comparisons
-- no new numeric threshold invented anywhere in this module):

  Manipulation (STRICT close, wick excursion alone does not qualify):
    Bullish hypothesis: close < range_low
    Bearish hypothesis: close > range_high
    The FIRST outside close owns the manipulation identity -- consecutive
    candles remaining outside the SAME side before reclaim are one
    manipulation excursion, not new manipulations (no state change, no
    identity change, on any of those follow-on candles).

  Reclaim (INCLUSIVE, no midpoint/equilibrium requirement):
    range_low <= close <= range_high
    A candle that jumps directly to the OPPOSITE side without first
    satisfying this inclusive reclaim (e.g. Bullish hypothesis, a later
    candle closes > range_high while still < range_low was the last
    state) does NOT count as reclaim NOR as Distribution (Distribution
    is explicitly defined as occurring "after reclaim" below) -- no
    state change on such a candle; the sequence keeps waiting for a
    genuine inclusive reclaim.

  Distribution (STRICT, only evaluated once stage == "reclaimed"):
    Bullish: close > range_high  (the first qualifying close confirms)
    Bearish: close < range_low
    A close beyond the ORIGINAL manipulation-side boundary instead
    (Bullish: close < range_low again; Bearish: close > range_high
    again) = "failed", using the SAME strict test Manipulation itself
    uses, just applied post-reclaim.

  Explicitly NOT gated on (per this fix's own locked rule): BOS, CHoCH,
  FVG, displacement, wick size, sustained-closes count, ATR magnitude,
  session/kill-zone timing. No SNR/breakout-retest price tolerance is
  reused for PO3 boundaries -- PO3 uses the EXACT canonical
  `range_high`/`range_low` BalanceRangeEngine already computed, no
  tolerance band added or invented.

TEMPORAL INTEGRITY: a Balance Range confirming at prefix-end index `i`
is computed from `candles[:i+1]` and `compute_atr(candles[:i+1])` ONLY --
never any candle after `i`. Manipulation/Reclaim/Distribution are only
ever tested on candles strictly AFTER the active range's own end_index,
so a candle being tested can never feed back into (or modify) the range
it is being tested against.

LIFECYCLE / STALE-IDENTITY (Fix #7AD's own locked rules):
  - One Balance Range may produce at most one PO3: once a candidate
    reaches "confirmed" or "failed" it is TERMINAL -- no further
    candle updates its evidence (the `elif` chain below simply has no
    branch for "confirmed"/"failed", so nothing touches a terminal
    candidate) until a NEWER Balance Range confirms and replaces it
    outright with a fresh "candidate".
  - "A newer canonical Balance Range supersedes an unfinished older
    candidate": whenever `detect_balance_range()` confirms a NEW range
    ending exactly at the current replay index, it immediately replaces
    whatever was active (even mid-manipulation or mid-reclaim) with a
    brand-new "candidate", discarding all prior manipulation/reclaim
    evidence. This is the literal, unqualified rule as given -- one
    accepted consequence (reported, not silently avoided): if a
    manipulation candle's own range/body is small enough that
    `detect_balance_range()` re-confirms a (shifted) compressed range
    anchored AT that very candle, the older candidate is superseded
    rather than treated as having been manipulated. This is a
    defensible reading of the rule, not a bug: if a fresh compressed
    range genuinely re-confirms at that index, price did not actually
    displace enough to blow the compression bound, which is itself
    weak evidence for a genuine manipulation excursion.
  - "No old Balance Range may pair with unrelated current movement
    after it has been consumed/superseded" is automatic: superseding or
    starting fresh always REPLACES the entire working dict (never
    mutates fields in place), so a consumed/superseded range's identity
    can never leak into a later candidate's evidence.
  - No arbitrary bar-count expiry is implemented (per this fix's own
    instruction) -- an unfinished candidate simply remains active
    (waiting) until either it completes (confirmed/failed) or a newer
    Balance Range supersedes it. There is deliberately no third way for
    an unfinished candidate to be discarded.

SEQUENCE-SELECTION RULE (reported explicitly, per this fix's own
requirement): the replay scans candle indices in chronological order;
the ACTIVE PO3 candidate at any point in the scan is always the most
recently confirmed Balance Range that has not yet reached a terminal
stage, or -- once terminal -- remains untouched until a still-newer
Balance Range confirms and replaces it. The function's return value is
this active candidate's state as of the LAST candle in the given window
(`candles[-1]`, "now").

DIRECTION / "AS OF NOW" (per this fix's own instruction): `hypothesis_
direction` is exposed the instant Manipulation begins (a HYPOTHESIS, not
a confirmed fact); `direction` is populated ONLY when `stage ==
"confirmed"`. A `stage == "confirmed"` result may describe Distribution
that completed several candles ago, not necessarily at `candles[-1]` --
this function reports the true, honest evidence (real distribution_index/
timestamp) regardless of how long ago it happened; it is the STRATEGY
layer's own responsibility (per this fix's own instruction: "Strategy
may fire only when the current/latest candle is the Distribution
confirmation event") to additionally check `distribution_index ==
len(candles) - 1` before firing -- the same separation of concerns this
codebase already uses elsewhere (a detector reports genuine evidence,
a Strategy decides eligibility/freshness on top of it)."""
from typing import Dict, List

from core.BalanceRangeEngine import MIN_RANGE_DURATION, detect_balance_range
from core.core_models import CandleSnapshot
from core.demand_engine import compute_atr

_NO_PO3: Dict = {
    "stage": "none",
    "hypothesis_direction": None,
    "direction": None,
    "range_start_index": None, "range_start_timestamp": None,
    "range_end_index": None, "range_end_timestamp": None,
    "range_high": None, "range_low": None,
    "manipulation_index": None, "manipulation_timestamp": None,
    "manipulation_open": None, "manipulation_high": None, "manipulation_low": None, "manipulation_close": None,
    "reclaim_index": None, "reclaim_timestamp": None,
    "reclaim_open": None, "reclaim_high": None, "reclaim_low": None, "reclaim_close": None,
    "distribution_index": None, "distribution_timestamp": None,
    "distribution_open": None, "distribution_high": None, "distribution_low": None, "distribution_close": None,
}


def _start_candidate(range_result: Dict) -> Dict:
    candidate = dict(_NO_PO3)
    candidate["stage"] = "candidate"
    candidate["range_start_index"] = range_result["start_index"]
    candidate["range_start_timestamp"] = range_result["start_timestamp"]
    candidate["range_end_index"] = range_result["end_index"]
    candidate["range_end_timestamp"] = range_result["end_timestamp"]
    candidate["range_high"] = range_result["range_high"]
    candidate["range_low"] = range_result["range_low"]
    return candidate


def detect_po3_sequence(candles: List[CandleSnapshot]) -> Dict:
    """Replays the canonical `detect_balance_range()` across every
    already-fetched prefix of `candles` to identify the currently-active
    PO3 candidate (if any) and its stage as of `candles[-1]`. See this
    module's own docstring for the full audit, locked rules, and
    lifecycle/stale-identity handling -- this function is the single
    entry point implementing all of it.

    Returns a dict with `stage` ("none"/"candidate"/"manipulation"/
    "reclaimed"/"confirmed"/"failed"), `hypothesis_direction` (set once
    Manipulation begins), `direction` (set ONLY when stage=="confirmed"),
    the active range's own start/end index/timestamp/high/low (straight
    from `detect_balance_range()`, never recomputed differently), and
    each of manipulation/reclaim/distribution's own real index/timestamp/
    OHLC once reached (None/False together otherwise)."""
    if len(candles) < MIN_RANGE_DURATION:
        return dict(_NO_PO3)

    active = dict(_NO_PO3)

    for i in range(MIN_RANGE_DURATION - 1, len(candles)):
        prefix = candles[:i + 1]
        range_result = detect_balance_range(prefix, compute_atr(prefix))

        if range_result["confirmed"] and range_result["end_index"] == i:
            # A fresh Balance Range confirms ending exactly here -- per
            # the locked rule, this ALWAYS supersedes an unfinished
            # candidate and ALWAYS replaces a terminal one. Candle i is
            # the range's own last candle (already inside range_high/
            # range_low by construction), never also tested against it.
            active = _start_candidate(range_result)
            continue

        if active["stage"] == "none" or i <= active["range_end_index"]:
            continue

        candle = candles[i]
        range_high = active["range_high"]
        range_low = active["range_low"]

        if active["stage"] == "candidate":
            if candle.close < range_low:
                active["stage"] = "manipulation"
                active["hypothesis_direction"] = "Bullish"
            elif candle.close > range_high:
                active["stage"] = "manipulation"
                active["hypothesis_direction"] = "Bearish"
            else:
                continue
            active["manipulation_index"] = i
            active["manipulation_timestamp"] = str(candle.timestamp)
            active["manipulation_open"] = candle.open
            active["manipulation_high"] = candle.high
            active["manipulation_low"] = candle.low
            active["manipulation_close"] = candle.close

        elif active["stage"] == "manipulation":
            if range_low <= candle.close <= range_high:
                active["stage"] = "reclaimed"
                active["reclaim_index"] = i
                active["reclaim_timestamp"] = str(candle.timestamp)
                active["reclaim_open"] = candle.open
                active["reclaim_high"] = candle.high
                active["reclaim_low"] = candle.low
                active["reclaim_close"] = candle.close
            # else: same excursion continues (same side), or a same-candle
            # jump straight to the opposite side without ever reclaiming
            # first -- neither changes state; manipulation identity is
            # never overwritten (first outside close owns it).

        elif active["stage"] == "reclaimed":
            direction = active["hypothesis_direction"]
            if direction == "Bullish" and candle.close > range_high:
                active["stage"] = "confirmed"
                active["direction"] = "Bullish"
                active["distribution_index"] = i
                active["distribution_timestamp"] = str(candle.timestamp)
                active["distribution_open"] = candle.open
                active["distribution_high"] = candle.high
                active["distribution_low"] = candle.low
                active["distribution_close"] = candle.close
            elif direction == "Bearish" and candle.close < range_low:
                active["stage"] = "confirmed"
                active["direction"] = "Bearish"
                active["distribution_index"] = i
                active["distribution_timestamp"] = str(candle.timestamp)
                active["distribution_open"] = candle.open
                active["distribution_high"] = candle.high
                active["distribution_low"] = candle.low
                active["distribution_close"] = candle.close
            elif direction == "Bullish" and candle.close < range_low:
                active["stage"] = "failed"
            elif direction == "Bearish" and candle.close > range_high:
                active["stage"] = "failed"
            # else: still within the range -- remains "reclaimed".

        # "confirmed"/"failed": terminal, no branch touches it -- only a
        # newer Balance Range confirming (checked at the top of the loop
        # every iteration) can ever replace it.

    return active
