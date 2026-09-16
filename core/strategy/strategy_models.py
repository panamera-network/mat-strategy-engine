from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict



@dataclass
class StrategySnapshot:
    symbol: str
    timeframe: str
    bias: str
    momentum: float
    strength: float
    suppression: bool
    suppression_reason: str
    structure_type: str
    structure_direction: str
    structure_valid: bool
    context_zone: str
    context_level: Optional[float]
    timestamp: datetime
    current_high: Optional[float] = None
    current_low: Optional[float] = None
    is_last_bias_candle: bool = False
    engulfing_sequence: Optional[List[str]] = None
    engulfing_strength: Optional[str] = None
    # Fix #7J -- audit of every committed SNR-field read found exactly 4
    # fields genuinely consumed by a committed Strategy
    # (BiasContinuationScalpingStrategy/BiasContinuationSwingStrategy, both
    # committed in Fix #7B): snr_context (compared against
    # "at_support"/"at_resistance"), nearest_support, nearest_resistance,
    # and snr_strength (a confidence bonus multiplier). Sourced from the
    # canonical StructureSnapshot.snr_levels (Fix #2's SMC engine) via
    # StrategyEngine.to_strategy_snapshot()'s _snr_context() helper -- no
    # new formula, no new fetch.
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    snr_context: str = "neutral"
    snr_strength: float = 0.0
    # Fix #6AS — canonical, instrument-scale-independent momentum, copied
    # straight from StructureSnapshot.atr_normalized_momentum (Fix #6V).
    # Additive only; the legacy `momentum` field above (clamped [0,10],
    # per-instrument price-unit) is untouched and still populated exactly
    # as before. None whenever the engine didn't have enough candles for a
    # genuine ATR14 -- never backfilled/guessed. No Strategy plugin reads
    # this yet (Fix #6AR's audit) -- this fix only exposes the value.
    # POST /core/evaluate's raw-JSON-body construction
    # (StrategySnapshot(**snapshot_data)) omitting this key simply falls
    # through to this default (None) -- no fallback from legacy `momentum`
    # is invented for a caller that doesn't supply it.
    atr_normalized_momentum: Optional[float] = None
    # Fix #7H — canonical structural-event evidence, copied straight from
    # StructureSnapshot.event_timestamp/event_index/event_broken_level
    # (Fix #2/#6C's guarantee: all three are None exactly when there's no
    # confirmed BOS/CHoCH, and all populated together when there is).
    # Additive only, no recomputation, no new fetch -- needed so a Strategy
    # plugin can build a chart_markings "structure" marking (Fix #7F/#7G)
    # without recomputing structural evidence independently. No existing
    # plugin reads these yet.
    event_timestamp: Optional[str] = None
    event_index: Optional[int] = None
    event_broken_level: Optional[float] = None
    # Fix #7K — standalone per-candle direction evidence (close vs open
    # only, no engulfing/relational comparison) for the most recent
    # candles, copied straight from StructureSnapshot.recent_candles (each
    # entry a plain {"direction", "index", "timestamp"} dict, converted
    # from the canonical CandleDirection dataclass). Additive only, no
    # recomputation, no new fetch -- needed so a candle-sequence Strategy
    # (e.g. IPC) can identify an exact multi-candle pattern without
    # recomputing candle history itself. Empty list when there aren't
    # enough candles yet, never guessed.
    recent_candles: Optional[List[Dict]] = None
    # Fix #7L — canonical pre-break trend evidence, copied straight from
    # StructureSnapshot.pre_break_trend (Fix #6C): the two-swing trend read
    # BEFORE the current structure event's break was evaluated -- exactly
    # what BOS/CHoCH was decided against. "Neutral" is a real, meaningful
    # value (a break with no established trend either way, i.e. a BOS
    # label that is a default/fallback rather than a substantiated
    # continuation claim), not a missing-evidence placeholder. None only
    # when there's no confirmed structure event at all, same convention as
    # event_timestamp/event_index/event_broken_level above. Additive only,
    # no recomputation, no new fetch -- needed so a Strategy plugin can
    # tell a genuine trend-continuation BOS (structure_direction agrees
    # with pre_break_trend) apart from a BOS-from-Neutral default without
    # recomputing structure evidence itself. No existing plugin reads this
    # yet.
    pre_break_trend: Optional[str] = None
    # Fix #7M — canonical active-zone evidence, copied straight from
    # StructureSnapshot.active_zone_* (Fix #4B/#5E3B's existing
    # select_active_zone() nearest-zone rule, exposed via the sibling
    # get_active_zone() that returns the zone object itself instead of
    # collapsing it to (type, level)). freshness/structural_evidence come
    # straight from the existing canonical derive_freshness_state()/
    # derive_structural_evidence() (Fix #5H2) -- no new touch/mitigation
    # logic, no new formula. Additive only, no recomputation, no new
    # fetch -- needed so a zone-driven Strategy (e.g. Fresh Zone Reaction)
    # can react to the zone's own top/bottom/freshness/timestamp/index
    # without recomputing zone detection/selection itself. None when
    # there's no active zone. No existing plugin reads these yet.
    active_zone_type: Optional[str] = None
    active_zone_top: Optional[float] = None
    active_zone_bottom: Optional[float] = None
    active_zone_freshness: Optional[str] = None
    active_zone_structural_evidence: Optional[str] = None
    active_zone_timestamp: Optional[str] = None
    active_zone_index: Optional[int] = None
    # Fix #7N — the active zone's own touch_count (Fix #5E3), straight
    # copy, no new counting logic. Supporting/transparency evidence only
    # -- NOT an eligibility gate for any strategy (see
    # MitigationSecondTouchStrategy's own audit note: freshness=="touched"
    # alone does not distinguish a true 2nd visit from a 3rd/4th+ one).
    # None when there's no active zone.
    active_zone_touch_count: Optional[int] = None
    # Fix #7N — a SEPARATE minimal evidence bundle from active_zone_*
    # above: the nearest valid-AND-mitigated zone (demand_engine's
    # get_nearest_mitigated_zone(), a sibling selector to get_active_zone()
    # -- neither get_active_zone() nor select_active_zone() are touched by
    # this; active_zone_* keeps meaning exactly what it always has, valid
    # AND NOT mitigated). Needed because a mitigated zone can never become
    # "the" active zone through get_active_zone()'s existing eligibility,
    # so a Strategy plugin that specifically wants mitigation evidence
    # needs this separate path. structural_evidence reuses the existing
    # canonical derive_structural_evidence() (Fix #5H2) unchanged, just
    # given this zone instead. None when there is no valid mitigated zone.
    mitigated_zone_type: Optional[str] = None
    mitigated_zone_top: Optional[float] = None
    mitigated_zone_bottom: Optional[float] = None
    mitigated_zone_structural_evidence: Optional[str] = None
    mitigated_zone_timestamp: Optional[str] = None
    mitigated_zone_index: Optional[int] = None
    mitigated_zone_touch_count: Optional[int] = None
    # Fix #7P — genuine breakout-then-later-retest evidence, copied
    # straight from StructureSnapshot.breakout_origin_*/retest_* (v1
    # BOS-only; see structure_utils.detect_breakout_retest()'s own
    # docstring for the full audit rationale). event_timestamp/event_index
    # above always point at the current/most-recent candle whenever
    # structure_valid is True -- they cannot prove WHEN a break originally
    # happened; breakout_origin_index/timestamp is the actual first-
    # crossing candle of the CURRENT breakout leg. Additive only, no
    # recomputation, no new fetch.
    breakout_origin_index: Optional[int] = None
    breakout_origin_timestamp: Optional[str] = None
    retest_index: Optional[int] = None
    retest_timestamp: Optional[str] = None
    retest_confirmed: bool = False
    # Fix #7S -- canonical conviction evidence, straight copy from
    # StructureSnapshot.conviction/conviction_direction (itself a straight
    # copy of this same (symbol, tf)'s already-computed StyleSnapshot.
    # conviction/direction, Fix #6AK -- see StructureSnapshot's own
    # docstring for the full wiring path). conviction is already [0,1],
    # direction-relative (opposition/no-direction floors to 0). No new
    # formula, no recomputation, no new fetch -- and no Strategy should
    # ever recompute it independently. conviction_direction uses
    # BiasEngine's bias_label vocabulary ("uptrend"/"downtrend"/"neutral"),
    # NOT the "Bullish"/"Bearish"/"Neutral" vocabulary `bias` above uses.
    conviction: Optional[float] = None
    conviction_direction: Optional[str] = None
    # Fix #7T -- genuine prior-CHoCH-before-this-BOS sequence evidence,
    # straight copy from StructureSnapshot.choch_confirmed/choch_index/
    # choch_timestamp/choch_broken_level (itself computed by structure_
    # utils.detect_choch_then_bos() -- see StructureSnapshot's own
    # docstring for the full audit/wiring path). event_index/
    # event_timestamp above always describe the CURRENT event only;
    # choch_index/choch_timestamp describe a different, earlier candle.
    # No new formula, no recomputation, no new fetch.
    choch_confirmed: bool = False
    choch_index: Optional[int] = None
    choch_timestamp: Optional[str] = None
    choch_broken_level: Optional[float] = None
    # Fix #7T (BOS origin identity audit) -- straight copy from
    # StructureSnapshot.bos_origin_index/bos_origin_timestamp (the true
    # origin of the current BOS leg, Fix #7P's own current-leg backward-
    # origin principle -- see StructureSnapshot's own docstring). Never
    # event_index/event_timestamp, which always describe "now" and may be
    # several candles later than where this BOS leg actually began.
    bos_origin_index: Optional[int] = None
    bos_origin_timestamp: Optional[str] = None
    # Fix #7U -- genuine expansion -> pullback -> recovery momentum
    # sequence evidence, straight copy from StructureSnapshot.momentum_
    # sequence_confirmed/momentum_sequence_direction/momentum_expansion_*/
    # momentum_pullback_*/momentum_recovery_* (itself computed by
    # MomentumEngine.detect_pullback_recovery() -- see StructureSnapshot's
    # own docstring for the full audit/wiring path). atr_normalized_
    # momentum above always describes the CURRENT reading only; the
    # expansion/pullback fields describe two different, earlier candles.
    # No new formula, no recomputation, no new fetch.
    momentum_sequence_confirmed: bool = False
    momentum_sequence_direction: Optional[str] = None
    momentum_expansion_index: Optional[int] = None
    momentum_expansion_timestamp: Optional[str] = None
    momentum_expansion_value: Optional[float] = None
    momentum_pullback_index: Optional[int] = None
    momentum_pullback_timestamp: Optional[str] = None
    momentum_pullback_value: Optional[float] = None
    momentum_recovery_index: Optional[int] = None
    momentum_recovery_timestamp: Optional[str] = None
    momentum_recovery_value: Optional[float] = None

def price_from_snapshot(snapshot: StrategySnapshot) -> Optional[float]:
    """A representative chart price for a signal — for placing a marker/zone
    on the y-axis. Prefers the zone/level price; falls back to the midpoint
    of the latest candle's high/low."""
    if snapshot.context_level is not None:
        return snapshot.context_level
    if snapshot.current_high is not None and snapshot.current_low is not None:
        return round((snapshot.current_high + snapshot.current_low) / 2, 5)
    return None


# Fix #6AT/#6AU — canonical momentum confidence ingredient, shared across
# all 7 live Strategy plugins (audited: the momentum term is identical in
# form and purpose everywhere it appears; only each plugin's other bonus
# terms are strategy-specific). No plugin calls this yet -- Fix #6AU only
# adds the helper.
#
# Only the two direction vocabularies actually held by a plugin's own
# "committed trade direction" variable at the point it would call this are
# accepted -- verified by reading all 7 plugin files, not guessed:
#   Bullish/Bearish -- BiasContinuationScalpingStrategy/BiasContinuationSwingStrategy's
#     `direction`, GroupedLastCandleBiasStrategy's `direction`,
#     LastCandleBiasStrategy's `last_direction`/`shift_direction`
#     (all sourced from StructureSnapshot.structure_direction or bias)
#   long/short -- DoubleEngulfingStrategy's `direction`,
#     ZoneContinuationStrategy's `direction`, ScalpingBiasCascade's
#     `trade_direction` (the final trade side, post any reversal mapping)
# Deliberately NOT case-insensitive and NOT extended to other vocabularies
# used elsewhere in this repo (e.g. "uptrend"/"downtrend", "buy"/"sell") --
# expected_direction is not optional and an unrecognized string is treated
# exactly like "Neutral": zero, never guessed into one bucket or the other.
_BULLISH_DIRECTIONS = {"Bullish", "long"}
_BEARISH_DIRECTIONS = {"Bearish", "short"}


def strategy_momentum_confidence(atr_normalized_momentum: Optional[float], expected_direction: str) -> float:
    """Canonical, instrument-scale-independent momentum confidence in
    [0, 1] -- Fix #6AT's audit: linear cap at 2.0 ATR (empirically low
    saturation rate, ~9-13% live/rolling across FX/JPY/metals/crypto/
    energy, unlike a 1.0 ATR cap's ~30-38%), agreement-gated against
    expected_direction (never negative on disagreement, matching the same
    pattern established for StyleSnapshot.compute_conviction() -- Fix
    #6AK). None (ATR14 unavailable), exact zero momentum, an unrecognized
    expected_direction, and sign disagreement all return 0.0 -- never
    guessed, never negative.
    """
    if atr_normalized_momentum is None or atr_normalized_momentum == 0.0:
        return 0.0
    if expected_direction in _BULLISH_DIRECTIONS:
        agrees = atr_normalized_momentum > 0
    elif expected_direction in _BEARISH_DIRECTIONS:
        agrees = atr_normalized_momentum < 0
    else:
        return 0.0
    if not agrees:
        return 0.0
    return min(abs(atr_normalized_momentum) / 2.0, 1.0)


class Strategy(ABC):
    @abstractmethod
    def react(
        self,
        snapshot: StrategySnapshot,
        context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        pass