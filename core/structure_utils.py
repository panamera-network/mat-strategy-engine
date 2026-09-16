"""Pure swing/structure detection helpers — no dependency on other core/
engines, so both BiasEngine.py and StructureEngine.py can import this
without creating an import cycle (StructureEngine pulls in SuppressionEngine,
which pulls in BiasEngine)."""
from typing import Dict, List, Tuple

from core.core_models import CandleDirection, CandleSnapshot, SNRLevel, SwingPoint

SWING_LOOKBACK = 20
SWING_WINDOW = 3


def find_swings(candles: List[CandleSnapshot], window: int = SWING_WINDOW) -> Tuple[List[int], List[int]]:
    """Returns (swing_high_indices, swing_low_indices) into `candles`.

    A swing high at i needs candles[i].high higher than `window` candles on
    both sides; a swing low needs candles[i].low lower than `window` candles
    on both sides. The most recent `window` candles can never be confirmed
    swings yet (not enough candles to their right) — that's expected.
    """
    swing_highs: List[int] = []
    swing_lows: List[int] = []
    n = len(candles)

    for i in range(window, n - window):
        left = candles[i - window:i]
        right = candles[i + 1:i + 1 + window]

        if all(candles[i].high > c.high for c in left) and all(candles[i].high > c.high for c in right):
            swing_highs.append(i)

        if all(candles[i].low < c.low for c in left) and all(candles[i].low < c.low for c in right):
            swing_lows.append(i)

    return swing_highs, swing_lows


def detect_trend(candles: List[CandleSnapshot], swing_highs: List[int], swing_lows: List[int]) -> str:
    """Bullish = higher highs + higher lows. Bearish = lower highs + lower lows."""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "Neutral"

    higher_high = candles[swing_highs[-1]].high > candles[swing_highs[-2]].high
    higher_low = candles[swing_lows[-1]].low > candles[swing_lows[-2]].low
    lower_high = candles[swing_highs[-1]].high < candles[swing_highs[-2]].high
    lower_low = candles[swing_lows[-1]].low < candles[swing_lows[-2]].low

    if higher_high and higher_low:
        return "Bullish"
    if lower_high and lower_low:
        return "Bearish"
    return "Neutral"


def _last_swing_label(candles: List[CandleSnapshot], swing_indices: List[int], is_high: bool) -> str:
    """Fix #5F2 — labels the LAST entry of a swing index list, reusing the
    exact same adjacent-swing comparison label_swing_points() already
    applies to every swing point (and detect_trend() already applies to
    the same [-1] vs [-2] pair internally) — no new rule, no new formula."""
    latest = candles[swing_indices[-1]]
    if len(swing_indices) < 2:
        return "LH" if is_high else "HL"
    previous = candles[swing_indices[-2]]
    if is_high:
        return "HH" if latest.high > previous.high else "LH"
    return "LL" if latest.low < previous.low else "HL"


def detect_structure_event(candles: List[CandleSnapshot], swing_highs: List[int], swing_lows: List[int]) -> Dict:
    """BOS = break in the direction of the existing trend (continuation).
    CHoCH = break against the existing trend (trend flip).

    `broken_level` (Fix #2) is the actual swing high/low price that was
    breached — last_swing_high/last_swing_low below were already computed
    for the comparisons, just exposed on the return value now, not a new
    calculation and not a formula change.

    Fix #5F2 — leg_origin_* (additive, no detection-formula change): the
    latest confirmed OPPOSING swing — the one NOT broken — which was
    already being computed as last_swing_low/last_swing_high below purely
    for the break comparison itself. This is the structural leg's origin
    (the swing the leg that produced this break started from) — not a
    demand/supply zone origin (a different engine, a different, unrelated
    concept) and not a displacement-candle detector (a possible future,
    more expensive refinement, not this one). None when there's no
    confirmed event.

    Fix #6C — pre_break_trend (additive, no detection-formula change): the
    `trend` value already computed below, exposed as-is — the two-swing
    trend read BEFORE this break was evaluated, i.e. exactly what BOS/CHoCH
    was decided against (Fix #6B's audit). "Neutral" is a real, meaningful
    value here, not a missing-evidence placeholder: it means a break
    occurred while no two-swing trend was established either way, which is
    exactly the edge case where today's BOS label is a default/fallback
    rather than a substantiated continuation claim (see Fix #6B Q2) — a
    consumer that wants to tell that case apart from a "true" BOS needs
    this field. None only when there is no confirmed event at all (same
    convention as leg_origin_*/broken_level above) — pre_break_trend is
    scoped to an actual break, so there is no "pre-break" moment to report
    without one."""
    no_event = {
        "type": "None", "direction": "Neutral", "valid": False, "index": len(candles) - 1, "broken_level": None,
        "leg_origin_index": None, "leg_origin_timestamp": None, "leg_origin_price": None, "leg_origin_swing_label": None,
        "pre_break_trend": None,
    }
    if not swing_highs or not swing_lows:
        return no_event

    last_swing_high = candles[swing_highs[-1]].high
    last_swing_low = candles[swing_lows[-1]].low
    curr = candles[-1]
    trend = detect_trend(candles, swing_highs, swing_lows)
    break_index = len(candles) - 1

    if curr.close > last_swing_high:
        event_type = "CHOCH" if trend == "Bearish" else "BOS"
        origin_index = swing_lows[-1]
        return {
            "type": event_type, "direction": "Bullish", "valid": True, "index": break_index, "broken_level": last_swing_high,
            "leg_origin_index": origin_index,
            "leg_origin_timestamp": str(candles[origin_index].timestamp),
            "leg_origin_price": last_swing_low,
            "leg_origin_swing_label": _last_swing_label(candles, swing_lows, is_high=False),
            "pre_break_trend": trend,
        }

    if curr.close < last_swing_low:
        event_type = "CHOCH" if trend == "Bullish" else "BOS"
        origin_index = swing_highs[-1]
        return {
            "type": event_type, "direction": "Bearish", "valid": True, "index": break_index, "broken_level": last_swing_low,
            "leg_origin_index": origin_index,
            "leg_origin_timestamp": str(candles[origin_index].timestamp),
            "leg_origin_price": last_swing_high,
            "leg_origin_swing_label": _last_swing_label(candles, swing_highs, is_high=True),
            "pre_break_trend": trend,
        }

    return no_event


def _find_current_leg_origin(candles: List[CandleSnapshot], current_index: int, level: float, direction: str) -> int:
    """Fix #7P's own origin-identity principle, extracted so it has exactly
    one implementation to reuse (Fix #7T reuses it too) rather than a
    second, independently-written copy of the same scan.

    Scans BACKWARD from `current_index` to find the START of the unbroken
    run of closes-beyond-`level` ending at `current_index` -- the origin
    of the CURRENT leg, not simply the earliest historical close-cross of
    the same numerical level. A candle further back whose close was on the
    wrong side of the level marks the end of any earlier, unrelated leg —
    scanning stops there rather than continuing past it, so a stale
    historical crossing already invalidated by that reversal can never be
    mistaken for the current origin. Returns `current_index` itself when
    the run has length 1 (no time has passed yet, the origin IS the
    current candle) — a real, valid answer, not a failure case; callers
    that specifically need "is there room for something AFTER the origin"
    (e.g. a retest) check that separately."""
    def beyond(c) -> bool:
        return c.close > level if direction == "Bullish" else c.close < level

    origin_index = 0
    for i in range(current_index - 1, -1, -1):
        if not beyond(candles[i]):
            origin_index = i + 1
            break
    return origin_index


def detect_breakout_retest(candles: List[CandleSnapshot], structure_event: Dict) -> Dict:
    """Fix #7P — genuine breakout-then-later-retest evidence, v1 BOS-only.

    Audit finding this function exists to fix: detect_structure_event()
    above evaluates ONLY candles[-1] against the current window's swing
    levels, so event_index/event_timestamp ALWAYS point at "now" (the most
    recent candle) whenever structure_valid is True — they never preserve
    WHEN a break originally happened relative to the present. A single
    snapshot's structure_event therefore cannot, by itself, prove "price
    broke this level several candles ago and is only now retesting it" —
    it can only prove "this exact candle satisfies the break condition".
    This function closes that gap by scanning the SAME already-fetched
    window for the break's true origin candle and any later retest,
    without re-deriving BOS-vs-CHoCH classification, trend, or swing
    points (all of which stay exclusively detect_structure_event()'s/
    detect_trend()'s/find_swings()'s job) — it only reuses:
      - structure_event's own already-decided valid/type/direction/
        broken_level (never recomputed here),
      - the IDENTICAL close-crosses-the-level comparison
        detect_structure_event() already uses for the current candle,
        scanned BACKWARD from the current candle to find where the
        CURRENT unbroken run of closes-beyond-the-level began — i.e. the
        origin of the leg actually being retested, not simply the
        earliest historical close-cross of the same numerical level (Fix
        #7P's own follow-up audit: an EARLIER, now-stale crossing of the
        same level that was later invalidated by price closing back
        through it must never be picked as the origin, even though it is
        numerically the first occurrence in the window),
      - the IDENTICAL wick-overlap tolerance convention already
        established for SNR level testing (max(candle_range * 0.25,
        abs(level) * 0.0003)), applied to the broken level instead of an
        SNR level -- inline here, no call to any SNR-specific function or
        classification (no SNRLevel object, no "tested"/"untested"
        status, no touch count) -- a purely geometric touch tolerance,
        nothing S&R-specific.

    v1 scope — BOS only: CHoCH represents a trend FLIP (the broken level
    is the origin of a brand new leg, not a continuation level being
    retested) — a materially different question this function does not
    attempt to answer (Fix #7P's own audit conclusion). structure_event
    that is not a valid BOS returns no evidence at all, deliberately, not
    a best-effort guess.

    "Holds" semantics: a touch only counts as a genuine retest if that
    candle's CLOSE stays on the broken side of the level (Bullish: close
    >= level; Bearish: close <= level) — a touch that closes through to
    the wrong side is a failed retest, not a valid one, and is skipped in
    favor of scanning for a later, genuine hold (if any).

    Returns a dict with breakout_origin_index/timestamp (the start of the
    CURRENT unbroken breakout leg, not the earliest historical crossing of
    the same level) and retest_index/timestamp/retest_confirmed — all
    None/False when there is no valid BOS, the origin IS the current
    candle (no time has passed for a retest yet), or no later candle both
    touches and holds."""
    no_evidence = {
        "breakout_origin_index": None, "breakout_origin_timestamp": None,
        "retest_index": None, "retest_timestamp": None, "retest_confirmed": False,
    }

    if not structure_event.get("valid") or structure_event.get("type") != "BOS":
        return no_evidence

    direction = structure_event.get("direction")
    level = structure_event.get("broken_level")
    if level is None or direction not in ("Bullish", "Bearish"):
        return no_evidence

    def beyond(c) -> bool:
        return c.close > level if direction == "Bullish" else c.close < level

    current_index = len(candles) - 1
    if not beyond(candles[current_index]):
        # structure_event's own valid=True/type="BOS" guarantees this is
        # true in practice (detect_structure_event() only classifies a
        # candle as a valid BOS when its own close satisfies this exact
        # condition) -- defensive only, never expected to fire live.
        return no_evidence

    # Fix #7P (origin-identity audit) — the origin of the CURRENT leg,
    # not simply the earliest historical close-cross of the same level.
    # See _find_current_leg_origin()'s own docstring for the full scan
    # rationale (also reused by Fix #7T for the same principle).
    origin_index = _find_current_leg_origin(candles, current_index, level, direction)

    if origin_index >= current_index:
        return no_evidence

    origin_candle = candles[origin_index]

    candle_range = abs(origin_candle.high - origin_candle.low)
    tolerance = max(candle_range * 0.25, abs(level) * 0.0003)

    retest_index = None
    for i in range(origin_index + 1, current_index):
        c = candles[i]
        touches = (c.low - tolerance) <= level <= (c.high + tolerance)
        if not touches:
            continue
        held = (c.close >= level) if direction == "Bullish" else (c.close <= level)
        if held:
            retest_index = i
            break

    if retest_index is None:
        return no_evidence

    retest_candle = candles[retest_index]
    return {
        "breakout_origin_index": origin_index,
        "breakout_origin_timestamp": str(origin_candle.timestamp),
        "retest_index": retest_index,
        "retest_timestamp": str(retest_candle.timestamp),
        "retest_confirmed": True,
    }


def detect_snr_breakout_retest(candles: List[CandleSnapshot], level: float, direction: str) -> Dict:
    """Fix #7W — generic S&R-level breakout-then-later-retest scan: the
    SAME current-leg-origin + touch-and-hold algorithm detect_breakout_
    retest() above uses for a structure break's broken_level, applied here
    to a plain (level, direction) pair with NO structure_event/BOS/CHoCH
    involved at all — so it can be reused for any S&R level, independent
    of whether that level was ever the subject of a BOS/CHoCH. Reuses
    _find_current_leg_origin() (one shared implementation, not a second
    independent one) and the identical wick-overlap tolerance
    detect_breakout_retest() already established
    (max(candle_range * 0.25, abs(level) * 0.0003)).

    "Holds" semantics, same as detect_breakout_retest(): a touch only
    counts as a genuine retest if that candle's CLOSE stays on the broken
    side of the level (Bullish: close >= level; Bearish: close <= level).

    Returns breakout_index/timestamp (the start of the CURRENT unbroken
    leg beyond `level`) and retest_index/timestamp/retest_confirmed — all
    None/False when `level`/`direction` are missing, the current candle
    isn't beyond the level, the origin IS the current candle (no time has
    passed for a retest yet), or no later candle both touches and holds.
    See detect_snr_role_flip() below for how this is applied across a full
    snr_levels list to find genuine role-flip evidence."""
    no_evidence = {
        "breakout_index": None, "breakout_timestamp": None,
        "retest_index": None, "retest_timestamp": None, "retest_confirmed": False,
    }
    if level is None or direction not in ("Bullish", "Bearish"):
        return no_evidence

    def beyond(c) -> bool:
        return c.close > level if direction == "Bullish" else c.close < level

    current_index = len(candles) - 1
    if not beyond(candles[current_index]):
        return no_evidence

    breakout_index = _find_current_leg_origin(candles, current_index, level, direction)
    if breakout_index >= current_index:
        return no_evidence

    breakout_candle = candles[breakout_index]
    candle_range = abs(breakout_candle.high - breakout_candle.low)
    tolerance = max(candle_range * 0.25, abs(level) * 0.0003)

    retest_index = None
    for i in range(breakout_index + 1, current_index):
        c = candles[i]
        touches = (c.low - tolerance) <= level <= (c.high + tolerance)
        if not touches:
            continue
        held = (c.close >= level) if direction == "Bullish" else (c.close <= level)
        if held:
            retest_index = i
            break

    if retest_index is None:
        return no_evidence

    retest_candle = candles[retest_index]
    return {
        "breakout_index": breakout_index,
        "breakout_timestamp": str(breakout_candle.timestamp),
        "retest_index": retest_index,
        "retest_timestamp": str(retest_candle.timestamp),
        "retest_confirmed": True,
    }


def detect_snr_role_flip(candles: List[CandleSnapshot], snr_levels: List[SNRLevel]) -> Dict:
    """Fix #7W — genuine S&R role-flip evidence: a canonical Resistance
    level genuinely broken by a close above it and later revisited and
    held as Support, or a canonical Support level broken by a close below
    it and later revisited and held as Resistance.

    Audit finding this function exists to fix: StrategyEngine._snr_context()
    (nearest_support/nearest_resistance/snr_context/snr_strength) only
    ever reports the CURRENT nearest level by proximity to "now" — it has
    no memory of whether a level was ever broken, nor of when. A single
    StrategySnapshot therefore cannot, by itself, prove "this used to be
    Resistance, price broke above it, and later came back down and held
    above it as Support" — only that some level is nearby right now.
    Deliberately NOT built on detect_structure_event()/detect_breakout_
    retest()'s structure_event: a BOS/CHoCH's broken_level is a swing-based
    STRUCTURE level, a different concept from an S&R level (this repo's own
    #7V/#7J audits already established snr_levels as the canonical S&R
    source — a level can be genuine S&R without ever being the specific
    level the most recent BOS/CHoCH broke). This function closes the gap
    using the SAME already-fetched `candles` window and the SAME already-
    derived `snr_levels` list (derive_snr_levels(), never recomputed or
    redefined here) — no new fetch, no new S&R detection.

    For each Resistance level: direction="Bullish" (closing back above an
    old Resistance is the "holds as Support" half of the flip). For each
    Support level: direction="Bearish" (closing back below an old Support
    is the "holds as Resistance" half). Each candidate is tested with
    detect_snr_breakout_retest() above, unmodified. Same-candle breakout/
    retest is structurally impossible (the retest scan there never
    includes the breakout index itself), and a stale, already-invalidated
    older breakout of the same level can never be reported instead of the
    current leg, for the same reason _find_current_leg_origin() already
    proves for Fix #7P/#7T.

    Multiple qualifying levels (rare — e.g. two different Resistance
    levels both technically satisfy this, or a Resistance and a Support
    candidate both qualify at once) are resolved by preferring the MOST
    RECENT retest_index — the freshest confirmed flip, not merely the
    first candidate in `snr_levels`' price-sorted order. This is a v1
    tie-break, not a claim that an older qualifying candidate is invalid.

    Returns confirmed/direction/original_role/new_role/level/
    breakout_index/breakout_timestamp/retest_index/retest_timestamp — all
    False/None together when no Resistance or Support level in
    `snr_levels` has a confirmed breakout+retest."""
    no_evidence = {
        "confirmed": False, "direction": None, "original_role": None, "new_role": None,
        "level": None, "breakout_index": None, "breakout_timestamp": None,
        "retest_index": None, "retest_timestamp": None,
    }
    best = None  # (retest_index, bundle) — prefer the most recent retest

    for lvl in snr_levels:
        if lvl.type == "Resistance":
            direction, original_role, new_role = "Bullish", "Resistance", "Support"
        elif lvl.type == "Support":
            direction, original_role, new_role = "Bearish", "Support", "Resistance"
        else:
            continue

        result = detect_snr_breakout_retest(candles, lvl.level, direction)
        if not result["retest_confirmed"]:
            continue
        if best is None or result["retest_index"] > best[0]:
            best = (result["retest_index"], {
                "confirmed": True, "direction": direction,
                "original_role": original_role, "new_role": new_role,
                "level": lvl.level,
                "breakout_index": result["breakout_index"],
                "breakout_timestamp": result["breakout_timestamp"],
                "retest_index": result["retest_index"],
                "retest_timestamp": result["retest_timestamp"],
            })

    return best[1] if best else no_evidence


def detect_choch_then_bos(candles: List[CandleSnapshot], current_event: Dict, window: int = SWING_WINDOW) -> Dict:
    """Fix #7T — genuine prior-CHoCH-before-current-BOS sequence evidence.

    Audit finding this function exists to fix: detect_structure_event()
    evaluates ONLY candles[-1] against the swing levels known from the
    FULL window it is given — it reports exactly one event, "as of right
    now". A single StructureSnapshot/StrategySnapshot therefore cannot, by
    itself, prove "a CHoCH happened several candles ago and this BOS
    happened later" — it can only prove "this exact candle satisfies a
    BOS break condition right now". There was no existing event-history
    mechanism anywhere in committed code (structure_utils.py has never
    exposed anything beyond the single current event; the only related
    additive evidence, Fix #7P's detect_breakout_retest(), answers a
    different question — breakout-then-retest of the SAME level, not a
    change-of-character followed by a LATER, different, continuation
    break).

    No new fetch and no persistent state were needed to close this gap:
    the SAME already-fetched candle window used for the current event
    (StructureEngine's 20-candle lookback) already contains enough raw
    history to answer "was there a same-direction CHoCH before this BOS"
    by replaying the exact canonical find_swings()/detect_structure_event()
    functions on progressively shorter PREFIXES of that same window —
    i.e. "what would structure detection have reported if evaluated as of
    each earlier candle" — never a hand-rolled reimplementation of
    swing/trend/BOS/CHoCH classification. This is deliberately a pure
    function over the given candle list only: calling it twice with the
    same candles and current_event always returns the same result
    (deterministic under repeated evaluation), and it carries no state of
    its own to leak across symbols or timeframes.

    current_event must be the caller's own already-decided
    detect_structure_event() result for the FULL `candles` window (never
    recomputed here). If current_event is not a valid BOS, there is by
    definition no "later BOS" for any sequence to end at, so this returns
    no evidence immediately -- a plain CHoCH with no later BOS, an invalid
    event, or a CHoCH-classified current_event are all rejected the same
    way, deliberately, not a best-effort guess.

    When current_event IS a valid BOS, scans strictly BACKWARD from the
    candle immediately before its break index (so a same-candle
    CHoCH/BOS collision is structurally impossible, not merely checked
    for) looking for the NEAREST earlier candle where a confirmed CHoCH
    in the SAME direction as current_event existed. An opposite-direction
    CHoCH, a BOS, or no event at some intermediate candle does not stop
    the scan -- only a same-direction CHoCH match does, or the window
    running out.

    Two-phase, mirroring Fix #7P's own origin-identity correction:
    finding the NEAREST match first (rather than the earliest one ever
    seen in the window) avoids picking a stale, already-superseded CHoCH
    from before some intervening reversal -- exactly the class of bug
    Fix #7P's audit found and fixed for breakout-origin identification.
    But the nearest matching candle is not necessarily where that CHoCH
    ORIGINALLY happened either: detect_structure_event() re-confirms the
    same break for every subsequent candle until the swing knowledge
    changes, so several consecutive candles right after a real CHoCH can
    all independently "look like" a fresh CHoCH when evaluated as their
    own prefix. Phase 2 continues scanning backward from the nearest
    match to find the earliest candle still reporting that SAME type/
    direction/broken_level -- the true origin of that specific CHoCH, not
    a later re-confirmation of it.

    v1 scope: only a CHoCH within this same bounded lookback window is
    ever found -- there is no sequence expiry / max-bars-between-events
    rule yet (deferred to a later rule audit), so a CHoCH further back
    than the window covers is indistinguishable from no CHoCH at all in
    this v1.

    BOS origin identity (Fix #7T's own follow-up audit, before this fix's
    first commit): current_event["index"] ALWAYS points at "now" (the
    most recent candle), exactly the same "now" vs true-origin gap Fix
    #7P's audit found and fixed for detect_breakout_retest(). A BOS leg
    can stay beyond its broken level for several more candles after the
    real break -- current_event["index"] would then describe a candle
    that merely still re-confirms an already-established break, not where
    the leg actually began. This function additionally reuses
    _find_current_leg_origin() (the SAME helper detect_breakout_retest()
    itself now uses, not a second independent implementation) to report
    the true origin of the CURRENT BOS leg as bos_origin_index/timestamp.
    The CHoCH scan above is entirely unchanged by this -- it still scans
    strictly before current_event["index"] ("now"), never before
    bos_origin_index; explicit testing (5 named timelines, including a
    BOS with several trailing closes beyond the level, a failed-then-
    renewed breakout, and a full opposite reversal before a same-
    direction re-confirmation) found the CHoCH search already correctly
    ends up strictly before the true BOS origin in every case, so
    narrowing its own scan boundary was not needed to fix the marking bug
    -- only the reported BOS candle itself was wrong.

    Ordering invariant (Fix #7T's own follow-up audit, before this fix's
    first commit): a confirmed sequence requires bos_origin_index STRICTLY
    GREATER than choch_index -- two distinct structural origins, the BOS
    leg's strictly later. A live-discovered edge case found
    bos_origin_index can otherwise equal choch_index: the exact same
    physical break candle can be a genuine CHoCH when evaluated against
    the swings known at its own point in time, then get relabeled a "BOS"
    for the current/full window once one more swing shifts the trend read
    to Neutral (Fix #6C's own Neutral-pre-break-trend default-to-
    continuation fallback) -- that is one break wearing two labels, not a
    real CHoCH-then-later-BOS sequence, and is rejected (choch_confirmed=
    False) rather than reported as confirmed.

    Returns a dict with choch_confirmed/choch_index/choch_timestamp/
    choch_broken_level/bos_origin_index/bos_origin_timestamp -- all
    False/None when current_event is not a valid BOS, no same-direction
    CHoCH is found within the window, or the found CHoCH and the BOS
    leg's origin turn out not to be strictly ordered (bos_origin_index >
    choch_index)."""
    no_evidence = {
        "choch_confirmed": False, "choch_index": None,
        "choch_timestamp": None, "choch_broken_level": None,
        "bos_origin_index": None, "bos_origin_timestamp": None,
    }

    if not current_event.get("valid") or current_event.get("type") != "BOS":
        return no_evidence

    direction = current_event.get("direction")
    bos_index = current_event.get("index")
    level = current_event.get("broken_level")
    if direction not in ("Bullish", "Bearish") or bos_index is None or level is None:
        return no_evidence

    min_len = window * 2 + 1

    def event_at(i: int) -> Dict:
        sub = candles[:i + 1]
        sh, sl = find_swings(sub, window=window)
        return detect_structure_event(sub, sh, sl)

    nearest_index = None
    nearest_level = None
    for i in range(bos_index - 1, min_len - 1, -1):
        event = event_at(i)
        if event["valid"] and event["type"] == "CHOCH" and event["direction"] == direction:
            nearest_index = i
            nearest_level = event["broken_level"]
            break

    if nearest_index is None:
        return no_evidence

    # Phase 2 — walk backward from the nearest match to find where this
    # SAME CHoCH (identical type/direction/broken_level) first appeared,
    # rather than reporting a later candle that merely still re-confirms
    # an already-established break.
    origin_index = nearest_index
    for i in range(nearest_index - 1, min_len - 1, -1):
        event = event_at(i)
        if event["valid"] and event["type"] == "CHOCH" and event["direction"] == direction and event["broken_level"] == nearest_level:
            origin_index = i
        else:
            break

    bos_origin_index = _find_current_leg_origin(candles, bos_index, level, direction)

    # Fix #7T (ordering-invariant audit) — a confirmed sequence requires
    # two DISTINCT structural origins, the BOS leg's strictly after the
    # CHoCH's. A live-discovered edge case found bos_origin_index can
    # equal choch_index: the SAME physical break candle can be a genuine
    # CHoCH when evaluated against the swings known at its own point in
    # time, and later get relabeled a "BOS" for the current/full window
    # once one more swing shifts the trend read to Neutral (Fix #6C's own
    # documented default-to-continuation fallback) -- that is one break
    # wearing two labels, not a real CHoCH-then-later-BOS sequence.
    # bos_origin_index < choch_index is not known to occur given the scan
    # above only ever matches a CHoCH strictly before "now" and origin-
    # scans backward from there, but is rejected here too rather than
    # trusted to be impossible by construction alone.
    if bos_origin_index <= origin_index:
        return no_evidence

    return {
        "choch_confirmed": True,
        "choch_index": origin_index,
        "choch_timestamp": str(candles[origin_index].timestamp),
        "choch_broken_level": nearest_level,
        "bos_origin_index": bos_origin_index,
        "bos_origin_timestamp": str(candles[bos_origin_index].timestamp),
    }



def label_swing_points(
    candles: List[CandleSnapshot],
    swing_highs: List[int],
    swing_lows: List[int],
) -> List[SwingPoint]:
    """HH/LH/LL/HL evidence for every confirmed swing point — price +
    index/timestamp. Independent of derive_snr_levels() below (which tags
    this same classification onto SNRLevel.source as a side effect of
    building resistance/support levels) so structure evidence doesn't
    require touching SNR level construction. Same classification rule,
    computed separately."""
    points: List[SwingPoint] = []

    for idx, swing_i in enumerate(swing_highs):
        label = "HH" if idx > 0 and candles[swing_i].high > candles[swing_highs[idx - 1]].high else "LH"
        points.append(SwingPoint(
            label=label,
            price=candles[swing_i].high,
            index=swing_i,
            timestamp=str(candles[swing_i].timestamp),
        ))

    for idx, swing_i in enumerate(swing_lows):
        label = "LL" if idx > 0 and candles[swing_i].low < candles[swing_lows[idx - 1]].low else "HL"
        points.append(SwingPoint(
            label=label,
            price=candles[swing_i].low,
            index=swing_i,
            timestamp=str(candles[swing_i].timestamp),
        ))

    points.sort(key=lambda p: p.index)
    return points


def derive_snr_levels(candles: List[CandleSnapshot], swing_highs: List[int], swing_lows: List[int], structure_event: Dict) -> List[SNRLevel]:
    levels: List[SNRLevel] = []

    for prev_i, cur_i in zip(swing_highs, swing_highs[1:]):
        if candles[cur_i].high > candles[prev_i].high:
            levels.append(SNRLevel(type="Resistance", level=candles[cur_i].high, source="HH"))

    for prev_i, cur_i in zip(swing_lows, swing_lows[1:]):
        if candles[cur_i].low < candles[prev_i].low:
            levels.append(SNRLevel(type="Support", level=candles[cur_i].low, source="LL"))

    levels.sort(key=lambda lvl: lvl.level)

    # Role reversal at the CHoCH point — the level nearest the break flips
    if structure_event.get("type") == "CHOCH" and levels:
        flip_target = min(levels, key=lambda lvl: abs(lvl.level - candles[-1].close))
        flip_target.type = "Support" if flip_target.type == "Resistance" else "Resistance"
        flip_target.source = "CHOCH_flip"

    return levels


def label_recent_candles(candles: List[CandleSnapshot], count: int = 3) -> List[CandleDirection]:
    """Fix #7K -- standalone bull/bear/neutral direction (close vs open on
    that candle alone -- no engulfing/relational comparison to a neighbor,
    unlike detect_engulfing_sequence()'s transition labels) for the last
    `count` candles, each with its absolute index (position in `candles`,
    same convention as SwingPoint/event_index) and timestamp.

    Added so a candle-sequence Strategy (e.g. IPC's Ignite/Pullback/
    Confirmation) can identify an exact 3-candle pattern from evidence
    already computed here, instead of recomputing candle direction/
    timestamp/index itself. Empty list (never a guess/backfill) when there
    aren't at least `count` candles yet.

    Fix #7R -- `volume` on each entry is the same candle's own
    CandleSnapshot.volume (MT5 tick volume), straight copy from this same
    already-fetched `candles` window -- no new fetch, no recomputation.
    """
    if len(candles) < count:
        return []

    window = candles[-count:]
    base_index = len(candles) - count
    result: List[CandleDirection] = []
    for offset, candle in enumerate(window):
        if candle.close > candle.open:
            direction = "bull"
        elif candle.close < candle.open:
            direction = "bear"
        else:
            direction = "neutral"
        result.append(CandleDirection(
            direction=direction, index=base_index + offset, timestamp=str(candle.timestamp),
            volume=candle.volume,
        ))
    return result
