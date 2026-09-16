from contextvars import Context
from dataclasses import  dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field



@dataclass
class CandleSnapshot:
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: str  # ISO 8601 or epoch
    range: float = field(init=False)
    body: float = field(init=False)
    bias: str = "neutral"
    suppressed: bool = False
    suppression_reason: str = ""

    def __post_init__(self):
        self.range = abs(self.high - self.low)
        self.body = abs(self.open - self.close)

    @property
    def conviction(self) -> float:
        return round(self.bias_score * 0.6 + self.strength_diagnostic.strength * 0.4, 2)

    @property
    def is_bullish(self) -> bool:
        return self.bias_label == "up"

    def summary(self) -> str:
        return f"{self.symbol} [{self.timeframe}] → Bias: {self.bias_label} ({self.bias_score}), Strength: {self.strength_diagnostic.strength}"

class StrengthDiagnostic:
    def __init__(self, strength: float, avg_body_ratio: float, momentum_slope: float):
        self.strength = strength
        self.avg_body_ratio = avg_body_ratio
        self.momentum_slope = momentum_slope

    def __lt__(self, other):
        if isinstance(other, (int, float)):
            return self.strength < other
        raise TypeError("Cannot compare StrengthDiagnostic with non-numeric type")

    def __repr__(self):
        return f"StrengthDiagnostic(strength={self.strength}, avg_body_ratio={self.avg_body_ratio}, momentum_slope={self.momentum_slope})"

    @property
    def body_dominance(self) -> float:
        """Fix #6O — canonical name for avg_body_ratio (Fix #6M/#6N's audit
        conclusion), raw [0,1] range, no ×10, no new formula. A read-only
        alias of the same stored value — not a second computation, so it
        can never drift from avg_body_ratio. avg_body_ratio remains the
        legacy name, untouched."""
        return self.avg_body_ratio

    def to_dict(self):
        return {
            "strength": self.strength,
            "avg_body_ratio": self.avg_body_ratio,
            "momentum_slope": self.momentum_slope,
            "body_dominance": self.body_dominance,
        }


@dataclass
class BiasSnapshot:
    symbol: str
    timeframe: str
    bias_score: float           # scaled -10 to +10 or normalized -1.0 to +1.0
    bias_label: str             # "up", "down", "neutral"
    strength_diagnostic: StrengthDiagnostic
    bias_sequence: List[float] = field(default_factory=list)
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    suppressed: bool = False
    suppression_reason: str = ""
    timestamp: Optional[str] = None

    @property
    def bias(self) -> float:
        return self.bias_score
    @property
    def strength(self) -> float:
        return self.strength_diagnostic.strength
    @property
    def parsed_timestamp(self) -> Optional[datetime]:
        if self.timestamp:
            return datetime.fromisoformat(self.timestamp)
        return None
    @property
    def label(self) -> str:
        return self.bias_label
    @property
    def score(self) -> float:
        return self
    
    def __post_init__(self):
        if not isinstance(self.strength_diagnostic, StrengthDiagnostic):
            raise TypeError(f"Expected StrengthDiagnostic, got {type(self.strength_diagnostic)}")



@dataclass
class MomentumSnapshot:
    symbol: str
    timeframe: str
    momentum: float           # scaled 0–10
    slope: float              # directional slope
    confidence_drop: bool = False
    score: float = 0.0        # raw float before scaling
    # Fix #6V — canonical signed, dimensionless momentum: slope2 (the same
    # 3-bar displacement `score` above is built from) divided by ATR14, no
    # clamp, no multiplier (Fix #6U's audit conclusion). None whenever
    # MomentumEngine.compute() wasn't given enough candles for a genuine
    # 14-period ATR (needs >=15) — deliberately not backfilled with a
    # different/shorter denominator. Additive only; momentum/slope/
    # score/confidence_drop above are unchanged and still computed exactly
    # as before.
    # Fix #6BB — acceleration/reversal/direction/divergence fields deleted
    # (confirmed fully dead by Fix #6BA's audit: zero repo-wide consumers,
    # never copied into StructureSnapshot/StyleSnapshot, never exposed via
    # any API route or serialization). The `acceleration` local variable
    # confidence_drop's formula depends on is unaffected — it was always a
    # plain local in MomentumEngine.compute(), never sourced from this
    # field.
    atr_normalized_momentum: float | None = None


class StructureLabel(str, Enum):
    BOS = "BOS"
    CHOCH = "CHOCH"
    NONE = "None"

class StrategyMode(str, Enum):
    SWING = "swing"
    SCALP = "scalp"
    RANGE = "range"
    BREAKOUT = "breakout"


@dataclass
class SwingPoint:
    """One confirmed swing high/low — HH/LH (highs) or LL/HL (lows) — with
    its price and its index/timestamp within the candle window StructureEngine
    evaluated. Same classification rule derive_snr_levels() already tags onto
    SNRLevel.source, exposed here standalone so it doesn't require touching
    SNR level construction."""
    label: str            # "HH", "LH", "LL", or "HL"
    price: float
    index: int             # index into the evaluated candle window
    timestamp: str | None = None


@dataclass
class CandleDirection:
    """Fix #7K -- one candle's standalone direction (close vs open only --
    no engulfing/relational comparison to a neighboring candle, unlike
    structure_utils.detect_engulfing_sequence()'s transition labels). Added
    so a Strategy plugin identifying an exact multi-candle sequence (e.g.
    IPC's Ignite/Pullback/Confirmation) can read each candle's direction,
    absolute index, and timestamp directly, instead of recomputing candle
    history itself. index is the candle's absolute position in the window
    StructureEngine evaluated (same convention as SwingPoint/event_index).

    Fix #7R -- `volume` is an additive field: the same candle's own
    CandleSnapshot.volume, straight copy, no recomputation. That field is
    MT5 tick volume (count of price-quote changes in the period) -- MT5
    also exposes a separate `real_volume` field which this pipeline has
    never fetched anywhere (mt5/fetcher.py only reads `tick_volume`); a
    live audit across the full symbol universe found `real_volume` is 0
    for every symbol regardless of asset class on this account's feed, so
    it carries no signal even if it were wired up. `volume` here must
    never be read as traded/real volume."""
    direction: str  # "bull", "bear", or "neutral"
    index: int
    timestamp: str
    volume: Optional[float] = None


@dataclass
class SNRLevel:
    type: str            # "Resistance" or "Support"
    level: float
    source: str          # "HH", "LL", "CHOCH_flip"
    valid: bool = True


@dataclass
class OrderBlock:
    type: str            # "Bullish" or "Bearish"
    high: float
    low: float
    open: float
    close: float
    timeframe: str
    valid: bool = True
    mitigated: bool = False


@dataclass
class FVG:
    type: str            # "Bullish" or "Bearish"
    top: float
    bottom: float
    timeframe: str
    valid: bool = True
    mitigated: bool = False


@dataclass
class StructureSnapshot:
    symbol: str
    timeframe: str
    current_high: float
    current_low: float
    prev_high: float
    prev_low: float
    current_zone: str
    prev_zone: str
    structure: str = "neutral"
    structure_type: str = field(init=False)
    structure_direction: str = field(init=False)
    structure_valid: bool = field(init=False)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context_zone: str = "neutral"
    context_level: float | None = None
    momentum: float = 0.0
    confidence_drop: bool = False
    # Fix #6V — canonical signed, dimensionless momentum (slope2/ATR14, no
    # clamp/multiplier), copied straight from MomentumEngine's
    # MomentumSnapshot.atr_normalized_momentum. None when MomentumEngine
    # didn't have enough candles for a genuine ATR14 — never backfilled
    # with a different denominator. Additive; the existing `momentum`
    # field above is untouched.
    atr_normalized_momentum: float | None = None
    strength: float = 0.0
    body_ratio: float = 0.0
    momentum_slope: float = 0.0
    suppression: bool = False
    suppression_reason: str = ""
    bias: str = "Neutral"
    snr_levels: List[SNRLevel] = field(default_factory=list)
    order_blocks: List[OrderBlock] = field(default_factory=list)
    fvg: List[FVG] = field(default_factory=list)
    # Fix #2 — structure evidence, exposed by StructureEngine only:
    # HH/HL/LH/LL swing points, and BOS/CHoCH event evidence (the level
    # broken, its index, and timestamp) beyond bare type/direction/valid.
    # event_index/event_timestamp are None when there's no valid event,
    # same as event_broken_level.
    swing_points: List[SwingPoint] = field(default_factory=list)
    event_broken_level: float | None = None
    event_index: int | None = None
    event_timestamp: str | None = None
    # Fix #5F2 — structural leg origin evidence: the latest confirmed
    # OPPOSING swing (the one NOT broken) that the leg producing this
    # BOS/CHoCH started from. Additive only — not a demand/supply zone
    # origin, not a displacement-candle detector, no history (single
    # current event only). None when there's no confirmed event.
    leg_origin_index: int | None = None
    leg_origin_timestamp: str | None = None
    leg_origin_price: float | None = None
    leg_origin_swing_label: str | None = None
    # Fix #5G1 — deterministic zone <-> leg origin link, minimal evidence
    # only (never the whole zone object): which zone (if any) was matched
    # as the likely origin of the current structural leg. See
    # core.demand_engine.link_zone_to_leg_origin() for the matching rule.
    # None when no zone matched (or no confirmed event at all).
    origin_zone_type: str | None = None
    origin_zone_timestamp: str | None = None
    origin_zone_top: float | None = None
    origin_zone_bottom: float | None = None
    # Fix #6C — the two-swing trend read BEFORE this event's break was
    # evaluated (see structure_utils.detect_structure_event()) — exactly
    # what BOS/CHoCH was decided against. "Neutral" is a real value (no
    # established trend either way at break time, per Fix #6B's audit);
    # None only when there's no confirmed event at all.
    pre_break_trend: str | None = None
    # Fix #7K -- standalone per-candle direction evidence for the most
    # recent candles (close vs open only, no engulfing/relational
    # comparison), needed by candle-sequence strategies (e.g. IPC's
    # Ignite/Pullback/Confirmation) to identify an exact multi-candle
    # pattern without recomputing candle history themselves. Populated by
    # structure_utils.label_recent_candles() from the same already-fetched
    # candle window used everywhere else in get_snapshot() -- no new fetch.
    # Empty list when there aren't enough candles yet, never guessed.
    recent_candles: List[CandleDirection] = field(default_factory=list)
    # Fix #7M — the canonical active zone's own evidence (type/top/bottom/
    # freshness/structural-evidence/timestamp/index), needed by a
    # zone-driven strategy (e.g. Fresh Zone Reaction) to react to the exact
    # zone already selected by demand_engine.get_active_zone() -- the SAME
    # nearest-zone selection rule select_active_zone() already uses for
    # context_zone/context_level (Fix #4B/#5E3B), just exposing the zone
    # object itself instead of collapsing it to (type, level). freshness/
    # structural_evidence come straight from the existing canonical
    # derive_freshness_state()/derive_structural_evidence() (Fix #5H2) --
    # no new touch/mitigation logic, no new formula. None when there is no
    # active zone for this symbol/timeframe.
    active_zone_type: str | None = None
    active_zone_top: float | None = None
    active_zone_bottom: float | None = None
    active_zone_freshness: str | None = None
    active_zone_structural_evidence: str | None = None
    active_zone_timestamp: str | None = None
    active_zone_index: int | None = None
    # Fix #7N — the active zone's own touch_count (Fix #5E3: distinct
    # wick-overlap visit episodes, straight copy, no new counting logic).
    # Exposed as supporting/transparency evidence only -- NOT an
    # eligibility gate for any strategy (see MitigationSecondTouchStrategy's
    # own audit note: freshness=="touched" alone does not distinguish a
    # true 2nd visit from a 3rd/4th+ one; touch_count lets a consumer see
    # the real count rather than the strategy silently overclaiming
    # precision the canonical evidence doesn't support). None when there
    # is no active zone.
    active_zone_touch_count: int | None = None
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
    mitigated_zone_type: str | None = None
    mitigated_zone_top: float | None = None
    mitigated_zone_bottom: float | None = None
    mitigated_zone_structural_evidence: str | None = None
    mitigated_zone_timestamp: str | None = None
    mitigated_zone_index: int | None = None
    mitigated_zone_touch_count: int | None = None
    # Fix #7P — genuine breakout-then-later-retest evidence (v1 BOS-only;
    # see structure_utils.detect_breakout_retest()'s own docstring for the
    # full audit rationale). event_index/event_timestamp above ALWAYS
    # point at the current/most-recent candle whenever structure_valid is
    # True -- they cannot prove WHEN a break originally happened relative
    # to now. breakout_origin_index/timestamp is the actual first-crossing
    # candle of the CURRENT breakout leg (not the earliest historical
    # crossing of the same numerical level); retest_index/timestamp is the
    # first later candle that both touches event_broken_level and closes
    # back on the held side. All None/False together when there is no
    # valid BOS, the origin IS the current candle (no time has passed for
    # a retest yet), or no later candle both touches and holds.
    breakout_origin_index: int | None = None
    breakout_origin_timestamp: str | None = None
    retest_index: int | None = None
    retest_timestamp: str | None = None
    retest_confirmed: bool = False
    # Fix #7S -- canonical conviction evidence, straight copy from this same
    # (symbol, tf)'s already-computed StyleSnapshot.conviction/direction
    # (StyleEngine.get_style_snapshot() -> StyleSnapshot.compute_conviction(),
    # Fix #6AK) -- set post-hoc by Output.py, the same pattern Fix #7C used
    # for `bias` above (StructureEngine itself has no StyleEngine
    # dependency; adding that edge here would create a cycle, since
    # StyleEngine already depends on StructureEngine). No recomputation, no
    # new formula, no new fetch -- StyleSnapshot for this exact (symbol, tf)
    # is already built by Output.py for the scalping/swing display blocks.
    # conviction is StyleSnapshot's own [0,1], direction-relative score
    # (opposition/no-direction floors to 0, never negative);
    # conviction_direction is StyleSnapshot.direction verbatim
    # ("uptrend"/"downtrend"/"neutral" -- BiasEngine's bias_label
    # vocabulary, NOT the "Bullish"/"Bearish"/"Neutral" vocabulary `bias`
    # above uses). Both None until Output.py's wiring runs (e.g. direct
    # StructureEngine.get_snapshot() calls that bypass Output.py, same
    # caveat as `bias` above per Fix #7C's own documented gap).
    conviction: float | None = None
    conviction_direction: str | None = None
    # Fix #7T -- genuine prior-CHoCH-before-this-BOS sequence evidence,
    # computed by structure_utils.detect_choch_then_bos() (replays the
    # canonical find_swings()/detect_structure_event() on shorter prefixes
    # of this same already-fetched lookback window -- no duplicate BOS/
    # CHoCH classification, no new fetch, no persistent state). event_
    # index/event_timestamp above ALWAYS describe the CURRENT/most-recent
    # confirmed event only; choch_index/choch_timestamp describe a
    # DIFFERENT, earlier candle -- the true origin of a same-direction
    # CHoCH found before the current event, only ever populated when the
    # current event is itself a valid BOS. All False/None together when
    # the current event is not a valid BOS, or no same-direction CHoCH
    # was found within the window (v1 scope -- no sequence expiry / max-
    # bars-between-events rule yet, deferred to a later rule audit).
    choch_confirmed: bool = False
    choch_index: int | None = None
    choch_timestamp: str | None = None
    choch_broken_level: float | None = None
    # Fix #7T (BOS origin identity audit, before this fix's first commit)
    # -- the true origin of the CURRENT BOS leg, computed via the SAME
    # current-leg backward-origin principle Fix #7P proved for
    # detect_breakout_retest() (structure_utils._find_current_leg_origin(),
    # one shared implementation, not a second independent one). event_
    # index/event_timestamp above always describe "now" -- a BOS can stay
    # beyond its broken level for several more candles after the real
    # break, so "now" is not necessarily where the leg began. Only ever
    # populated together with choch_confirmed=True (same convention as
    # choch_index/choch_timestamp above).
    bos_origin_index: int | None = None
    bos_origin_timestamp: str | None = None
    # Fix #7U -- genuine expansion -> pullback -> recovery momentum
    # sequence evidence, computed by MomentumEngine.detect_pullback_
    # recovery() (replays the canonical slope2/ATR14 formula -- the same
    # one atr_normalized_momentum above already uses -- on shorter
    # prefixes of this same already-fetched candle window; no duplicate
    # formula, no new fetch, no persistent state). atr_normalized_momentum
    # above ALWAYS describes the CURRENT/most-recent reading only;
    # momentum_expansion_*/momentum_pullback_* describe two DIFFERENT,
    # earlier candles -- the true origins of a same-direction expansion
    # and a later pullback found before the current (recovery) reading.
    # All None/False together when the current reading is missing, not
    # genuinely recovered (>= RECOVERY_STRONG_THRESHOLD), or no valid
    # earlier pullback+expansion pair was found within the window.
    momentum_sequence_confirmed: bool = False
    momentum_sequence_direction: str | None = None
    momentum_expansion_index: int | None = None
    momentum_expansion_timestamp: str | None = None
    momentum_expansion_value: float | None = None
    momentum_pullback_index: int | None = None
    momentum_pullback_timestamp: str | None = None
    momentum_pullback_value: float | None = None
    momentum_recovery_index: int | None = None
    momentum_recovery_timestamp: str | None = None
    momentum_recovery_value: float | None = None
    # Fix #7V -- the current/most-recent candle's own CLOSE price, straight
    # copy of the same already-fetched current candle current_high/
    # current_low above already use (candles[-1]). Needed so a Strategy
    # plugin can determine whether the current candle CLOSED back on the
    # favorable side of a level (a genuine hold/rejection) rather than
    # merely touching it with a wick -- current_high/current_low alone
    # cannot answer that. No new fetch, no recomputation.
    current_close: float | None = None
    # Fix #7W — genuine S&R role-flip evidence (Resistance broken bullishly
    # and later held as Support, or Support broken bearishly and later
    # held as Resistance), computed by structure_utils.detect_snr_role_
    # flip() over this same already-derived snr_levels list and the same
    # already-fetched candle window (no new fetch, no new S&R detection,
    # not coupled to any BOS/CHoCH structure_event). snr_flip_direction is
    # "Bullish"/"Bearish" (structure-layer vocabulary, same as
    # structure_direction/choch_* above) describing which side broke out,
    # not the eventual long/short trade direction a Strategy derives from
    # it. All None/False together when no Resistance or Support level in
    # snr_levels has a confirmed breakout-then-retest.
    snr_flip_confirmed: bool = False
    snr_flip_direction: str | None = None
    snr_flip_original_role: str | None = None
    snr_flip_new_role: str | None = None
    snr_flip_level: float | None = None
    snr_flip_breakout_index: int | None = None
    snr_flip_breakout_timestamp: str | None = None
    snr_flip_retest_index: int | None = None
    snr_flip_retest_timestamp: str | None = None

    @property
    def body_dominance(self) -> float:
        """Fix #6O — canonical name for body_ratio (Fix #6M/#6N's audit
        conclusion), raw [0,1] range, no ×10, no new formula. A read-only
        alias of the same stored value (set from StrengthDiagnostic.
        avg_body_ratio in StructureEngine.get_snapshot()) — not a second
        computation, so it can never drift from body_ratio. body_ratio
        remains the legacy name, untouched."""
        return self.body_ratio

    def __post_init__(self):
        self.structure_type = self.detect_structure_label()
        self.structure_direction = self.infer_direction()
        self.structure_valid = self.structure_type in ["CHOCH", "BOS"]

    def detect_structure_label(self) -> str:
        if self.prev_zone in ["HH", "HL"] and self.current_low < self.prev_low:
            return "CHOCH"
        elif self.prev_zone in ["LL", "LH"] and self.current_high > self.prev_high:
            return "CHOCH"
        elif self.prev_zone == "HL" and self.current_high > self.prev_high:
            return "BOS"
        elif self.prev_zone == "LL" and self.current_low < self.prev_low:
            return "BOS"
        return "None"

    def infer_direction(self) -> str:
        if self.structure_type == "CHOCH":
            return "Bearish" if self.current_low < self.prev_low else "Bullish"
        elif self.structure_type == "BOS":
            return "Bullish" if self.current_high > self.prev_high else "Bearish"
        return "Neutral"


    @property
    def label_weight(self) -> float:
        return {
            "BOS": 1.0,
            "CHOCH": 0.7,
            "None": 0.0
        }.get(self.label, 0.0)


@dataclass
class DiagnosticSnapshot:
    candle: CandleSnapshot
    context: Context
    bias: BiasSnapshot
    momentum: MomentumSnapshot
    structure: StructureSnapshot
    strength: StrengthDiagnostic
    suppression: List[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "active"


@dataclass
class StyleSnapshot:
    symbol: str
    timeframe: str
    mode: str  # "swing" or "scalping"
    direction: str
    momentum: float
    bias: float
    structure_label: Optional[str] = None
    # Fix #6AK — the BOS/CHoCH break's own direction ("Bullish"/"Bearish"/
    # "Neutral"), copied from StructureSnapshot.structure_direction. Needed
    # so compute_conviction()'s structure term can check agreement with
    # this snapshot's own labeled `direction` instead of rewarding any
    # BOS/CHoCH regardless of which way it broke (Fix #6AI/#6AH's finding).
    structure_direction: Optional[str] = None
    shift_confirmed: bool = False
    shift_direction: str = "bearish"
    shift_color: str = "#cccccc"
    # Fix #6D — canonical names for the same wick-touch-a-zone signal above
    # (see core.ShiftEngine.detect_zone_interaction()). shift_confirmed/
    # shift_direction/shift_color are kept as legacy aliases, set to the
    # exact same values, so existing diagnostic/alignment consumers reading
    # the old names are unaffected by this rename.
    zone_interaction: bool = False
    zone_interaction_direction: str = "Neutral"
    zone_interaction_color: str = "#cccccc"
    # Fix #6Z — canonical signed, dimensionless momentum evidence
    # (slope2/ATR14, no clamp/multiplier), copied from
    # StructureSnapshot.atr_normalized_momentum (see StyleEngine.py). None
    # when unavailable. Additive only — `momentum` above (the legacy raw
    # score) is untouched; only the display band/color path (Output.py)
    # reads this new field, not conviction/alignment/suppression.
    atr_normalized_momentum: float | None = None
    demand: str = "neutral"
    duration: str = "0 min"
    conviction: float = 0.0
    conviction_breakdown: dict[str, float] = field(default_factory=dict)
    suppression: bool = False

    def __post_init__(self):
        self.compute_conviction()

    # Fix #6AK — conviction redesigned per Fix #6AH/#6AI's audits:
    # conviction = confidence in THIS snapshot's own labeled `direction`,
    # bounded [0,1], never negative. Every term below is agreement-gated
    # against `direction` and floors to 0 on opposition or when no
    # directional call exists (`direction == "neutral"`) -- there is no
    # final emergency clamp anywhere in this method; each term is already
    # bounded to its own weight slice, and the per-mode weights (0.4+0.3+0.3
    # swing, 0.5+0.3+0.2 scalping) already sum to exactly 1.0, so the total
    # naturally lands in [0,1] by construction. `direction` itself uses two
    # different vocabularies depending on its source ("uptrend"/"downtrend"/
    # "neutral" from BiasEngine for this field; "Bullish"/"Bearish"/
    # "Neutral" from StructureEngine/ShiftEngine for structure_direction/
    # shift_direction) -- _is_bullish()/_is_bearish() below recognize both.
    def _is_bullish(self) -> bool:
        return self.direction in ("uptrend", "bullish", "Bullish")

    def _is_bearish(self) -> bool:
        return self.direction in ("downtrend", "bearish", "Bearish")

    def compute_conviction(self):
        is_bullish = self._is_bullish()
        is_bearish = self._is_bearish()
        has_direction = is_bullish or is_bearish

        if self.mode == "swing":
            # Structure term (max 0.4) — BOS=1.0/CHoCH=0.7 magnitude,
            # rewarded only when the break's own direction agrees with
            # this snapshot's labeled direction; opposing, missing, or
            # neutral structure contributes 0, never a penalty.
            structure_weight = {"BOS": 1.0, "CHOCH": 0.7}.get(self.structure_label or "None", 0.0)
            structure_agrees = (
                (is_bullish and self.structure_direction == "Bullish") or
                (is_bearish and self.structure_direction == "Bearish")
            )
            structure_component = (structure_weight * 0.4) if (has_direction and structure_agrees) else 0.0

            # Bias term (max 0.3) — magnitude only; bias and `direction`
            # are structurally the same evidence (both derived from the
            # same BiasEngine.evaluate_bias() call), so bias can never
            # oppose `direction` in practice (Fix #6AH's audit) -- abs()
            # is used rather than a redundant always-true agreement check.
            # min(...,1.0) bounds this term to its own weight slice
            # explicitly, rather than relying on bias_score's upstream
            # +/-10 invariant (BiasEngine.py) to keep it in range.
            bias_component = min(abs(self.bias / 10), 1.0) * 0.3 if has_direction else 0.0

            # Zone/demand term (max 0.3) — direction-relative fold of the
            # existing demand_score in [-2,+2]: only the half of the scale
            # that agrees with `direction` counts, the other half (and
            # neutral) contributes 0.
            demand_map = {"strong buy": +2, "buy": +1, "neutral": 0, "sell": -1, "strong sell": -2}
            demand_score = demand_map.get(self.demand.lower(), 0)
            if is_bullish:
                zone_component = max(demand_score, 0) / 2 * 0.3
            elif is_bearish:
                zone_component = max(-demand_score, 0) / 2 * 0.3
            else:
                zone_component = 0.0

            self.conviction_breakdown = {
                "structure": round(structure_component, 2),
                "bias": round(bias_component, 2),
                "zone_score": round(zone_component, 2),
            }

        elif self.mode == "scalping":
            # Momentum term (max 0.5) — canonical atr_normalized_momentum,
            # rewarded only when its sign agrees with `direction`. The
            # normalization (/2.0, capped at 1.0) bounds only this
            # CONTRIBUTION -- atr_normalized_momentum itself stays
            # unclamped everywhere else (MomentumEngine.py, momentum_band/
            # momentum_conf/momentum_pct, Alignment). None or opposing
            # sign -> 0, never a penalty.
            atr = self.atr_normalized_momentum
            momentum_agrees = (
                atr is not None and (
                    (is_bullish and atr > 0) or (is_bearish and atr < 0)
                )
            )
            momentum_component = (min(abs(atr) / 2.0, 1.0) * 0.5) if (has_direction and momentum_agrees) else 0.0

            # Shift term (max 0.3) — Fix #6AK also fixes the ordering bug
            # (Fix #6AI's audit) that made this permanently 0 in
            # production: shift_confirmed/shift_direction are now real,
            # final evidence at construction time (see StyleEngine.py),
            # not dataclass defaults. Rewarded only when the zone touch's
            # own direction agrees with `direction`.
            shift_agrees = (
                (is_bullish and self.shift_direction == "Bullish") or
                (is_bearish and self.shift_direction == "Bearish")
            )
            shift_component = 0.3 if (has_direction and self.shift_confirmed and shift_agrees) else 0.0

            # Bias term (max 0.2) — same reasoning as swing's bias term.
            bias_component = min(abs(self.bias / 10), 1.0) * 0.2 if has_direction else 0.0

            self.conviction_breakdown = {
                "momentum": round(momentum_component, 2),
                "shift": round(shift_component, 2),
                "bias": round(bias_component, 2),
            }

        else:
            self.conviction_breakdown = {}

        # Fix #6AK — breakdown is the source of truth: each component is
        # already rounded to the existing 2dp convention above, and
        # conviction is the rounded SUM of those already-rounded values,
        # so breakdown always reconciles exactly with the exposed
        # conviction (Fix #6AG's audit found the old breakdown never
        # matched conviction for scalping mode at all).
        self.conviction = round(sum(self.conviction_breakdown.values()), 2)


        

class PriceSnapshot(BaseModel):
    symbol: str
    timeframe: str
    high: float
    low: float
    prev_high: float
    prev_low: float


class BiasShiftEvent(BaseModel):
    symbol: str
    timeframe: str
    previous_bias: str
    new_bias: str
    trigger: str
    confirmed: bool
    momentum: float
    confidence_drop: bool
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    suppression: List[str]
    zone: Optional[str]
    structure: Optional[str]
    direction: str


class StrategySnapshot(BaseModel):
    mode: str
    conviction: float
    reasons: list[str]
    suppressed: bool = False
    fallback: Optional[str] = None

class StrategyResponse(BaseModel):
    bias: dict
    scalping: dict
    swing: dict