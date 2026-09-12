from dataclasses import dataclass
from typing import List, Optional, Tuple

from core.CandleEngine import CandleEngine
from core.core_models import CandleSnapshot, SwingPoint
from core.structure_utils import SWING_WINDOW

ATR_PERIOD = 14
BODY_ATR_RATIO = 0.6  # candle body must exceed 60% of ATR to mark a zone

# Fix #5B — seconds per candle, keyed the same as everywhere else under
# /core (M1..MN1). Local to this module rather than importing
# mt5/timeframes.py, which pulls in the MetaTrader5 package at import time —
# classify_zone()/classify_zones() below stay pure and testable without a
# live MT5 connection, same as the rest of this file. MN1 approximated as a
# flat 30 days.
TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
    "W1": 604800,
    "MN1": 2592000,
}


@dataclass
class SupplyDemandZone:
    type: str            # "demand" or "supply"
    top: float
    bottom: float
    # Fix #5E3 — valid is now derived from invalidated (valid = not
    # invalidated), decoupled from mitigated. A zone can be mitigated
    # (touched/closed-into) while still valid, until price actually closes
    # through the distal boundary.
    valid: bool = True
    # Fix #5D1 — renamed from "strength": this is the originating candle's
    # body-to-ATR ratio (impulse size), not a zone-quality/conviction
    # score — nothing (selector, classification, strategy) reads it as
    # such, and it must not be treated as one. Formula unchanged.
    impulse_strength: float = 0.0
    # Fix #5E3 — True once at least one later candle's CLOSE lands inside
    # [bottom, top] (a soft "this level was closed back into" signal).
    # No longer tied to valid/invalidated.
    mitigated: bool = False
    # Fix #5E3 — True once a later candle's CLOSE breaches the zone's
    # distal boundary (demand: close < bottom; supply: close > top) — the
    # decisive "this level failed" signal. valid is exactly `not invalidated`.
    invalidated: bool = False
    # Fix #5B — pattern adopted as canonical (minimum needed for
    # classification below); candle_index deliberately left out — still
    # WIP-only, not needed for reversal/continuation/unknown.
    pattern: str = ""
    # Fix #5E3 — renamed from "touches", and redefined: counts distinct
    # visit EPISODES (wick-inclusive contact), not raw candle occurrences.
    # Consecutive candles overlapping the zone are one visit; exiting then
    # re-entering starts a new one. status (WIP-only "tested"/"untested"
    # string) is dropped entirely — fully derivable from touch_count/
    # mitigated/invalidated wherever a display label is actually needed.
    touch_count: int = 0
    timestamp: str | None = None
    # Additive location-in-move label: "reversal", "continuation", or
    # "unknown". Not set by detect_zones() itself (zone detection/
    # thresholds/boundaries unchanged) — filled in afterward by
    # classify_zone()/classify_zones(), which need StructureEngine's
    # swing_points and are not wired into any live caller yet.
    classification: str = "unknown"


def compute_atr(candles: List[CandleSnapshot], period: int = ATR_PERIOD) -> float:
    """Average True Range over the most recent `period` candles."""
    if len(candles) < 2:
        return 0.0

    true_ranges = []
    for i in range(1, len(candles)):
        high, low = candles[i].high, candles[i].low
        prev_close = candles[i - 1].close
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    recent = true_ranges[-period:]
    return sum(recent) / len(recent) if recent else 0.0


def detect_zones(candles: List[CandleSnapshot]) -> List[SupplyDemandZone]:
    """Demand/supply zones from strong-bodied candles (body > 60% of ATR).
    Freshness (Fix #5E3): mitigated once a later candle closes back inside
    the zone; invalidated (and no longer valid) once a later candle closes
    through the zone's distal boundary; touch_count tracks distinct
    wick-overlap visit episodes. See SupplyDemandZone field comments."""
    atr = compute_atr(candles)
    if atr <= 0:
        return []

    zones: List[SupplyDemandZone] = []

    for i, c in enumerate(candles):
        body = abs(c.close - c.open)
        if body <= atr * BODY_ATR_RATIO:
            continue

        if c.close > c.open:
            zone = SupplyDemandZone(
                type="demand",
                top=c.open,
                bottom=c.low,
                impulse_strength=round(body / atr, 2),
                pattern=_zone_pattern(candles, i, "demand"),
                timestamp=str(c.timestamp),
            )
        else:
            zone = SupplyDemandZone(
                type="supply",
                top=c.high,
                bottom=c.open,
                impulse_strength=round(body / atr, 2),
                pattern=_zone_pattern(candles, i, "supply"),
                timestamp=str(c.timestamp),
            )

        # Fix #5E3 — canonical freshness model: touch_count tracks distinct
        # visit episodes (wick-inclusive overlap; a run of consecutive
        # overlapping candles is one visit, exiting and re-entering starts
        # a new one), mitigated fires on the first close-inside-zone candle
        # (a soft "was closed back into" signal), and invalidated fires on
        # the first close through the zone's distal boundary (a decisive
        # failure) — scanning stops there since the zone's life is over.
        in_visit = False
        for later in candles[i + 1:]:
            overlaps = later.low <= zone.top and later.high >= zone.bottom
            if overlaps:
                if not in_visit:
                    zone.touch_count += 1
                    in_visit = True
            else:
                in_visit = False

            if zone.bottom <= later.close <= zone.top:
                zone.mitigated = True

            if zone.type == "demand" and later.close < zone.bottom:
                zone.invalidated = True
                zone.valid = False
                break
            if zone.type == "supply" and later.close > zone.top:
                zone.invalidated = True
                zone.valid = False
                break

        zones.append(zone)

    return zones


def _direction(candle: CandleSnapshot, atr: float = 0.0) -> str:
    """Fix #5B — minimum helper needed for _zone_pattern() below (pattern
    is now canonical). Not exposed/used for anything else."""
    body = abs(candle.close - candle.open)
    if atr > 0 and body < atr * 0.25:
        return "base"
    if candle.close > candle.open:
        return "rally"
    if candle.close < candle.open:
        return "drop"
    return "base"


def _zone_pattern(candles: List[CandleSnapshot], index: int, zone_type: str) -> str:
    """Fix #5B — RBR/DBD/DBR/RBD: direction of the candle immediately
    before and after the zone candle. Uses `index` as a local loop position
    only (not stored on the zone — candle_index stays WIP-only, not part
    of this fix)."""
    if index <= 0 or index >= len(candles) - 1:
        return "RBR" if zone_type == "demand" else "DBD"

    local = candles[max(0, index - 2): min(len(candles), index + 3)]
    local_atr = compute_atr(local, period=max(2, len(local) - 1))
    before = _direction(candles[index - 1], local_atr)
    after = _direction(candles[index + 1], local_atr)

    if before == "rally" and after == "rally":
        return "RBR"
    if before == "drop" and after == "drop":
        return "DBD"
    if before == "drop" and after == "rally":
        return "DBR"
    if before == "rally" and after == "drop":
        return "RBD"

    return "RBR" if zone_type == "demand" else "DBD"


def select_active_zone(zones: List[SupplyDemandZone], current_price: float) -> Tuple[str, Optional[float]]:
    """Canonical DemandEngine context selector (Fix #4B) — the single zone-
    selection rule for this engine. Picks the active (fresh, valid) zone
    nearest to current_price; distance is 0 if current_price sits inside
    [bottom, top]. On a distance tie, the LATER zone in `zones` wins — list
    position only, not candle_index/timestamp (WIP-only fields this
    canonical selector deliberately does not depend on).
    demand level = top (proximal edge, price approaches from above);
    supply level = bottom (proximal edge, price approaches from below).
    No active zone -> ("neutral", None). Wired into StructureEngine via
    get_context() (Fix #4C/#4D3) — the legacy detect_snd() heuristic in
    structure_utils.py has since been removed (Fix #4E1).

    Fix #5E3B — eligibility is `valid AND NOT mitigated` (Fix #5E3A found
    a mitigated-but-valid zone was being selected identically to a fresh
    one, with no way for downstream consumers — EntrySuggestionEngine,
    the strategies, ShiftEngine — to know the level had already been
    touched). touch_count is deliberately not used for ranking here — this
    is a plain eligibility gate, not a quality score. invalidated has no
    new logic of its own; valid (`not invalidated`) already gates that.
    The raw zone objects this reads are untouched — a zone can still
    legitimately be `mitigated=True, valid=True` in the canonical data;
    this selector now simply excludes it from being the active context."""
    active = [z for z in zones if z.valid and not z.mitigated]
    if not active:
        return "neutral", None

    def distance(zone: SupplyDemandZone) -> float:
        if zone.bottom <= current_price <= zone.top:
            return 0.0
        if current_price < zone.bottom:
            return zone.bottom - current_price
        return current_price - zone.top

    nearest = active[0]
    nearest_distance = distance(nearest)
    for zone in active[1:]:
        d = distance(zone)
        if d <= nearest_distance:  # <=, not < — later zone wins on a tie
            nearest = zone
            nearest_distance = d

    level = nearest.top if nearest.type == "demand" else nearest.bottom
    return nearest.type, level


def _swing_tolerance_seconds(timeframe: str, window: int = SWING_WINDOW) -> int:
    """Fix #5B — deterministic timestamp tolerance for zone classification:
    `window` candles' worth of time on `timeframe` — the same confirmation
    window StructureEngine's find_swings() itself uses (SWING_WINDOW candles
    on each side of a swing point), so a zone counts as "near" a swing only
    within the same margin structure detection already tolerates.
    Unknown/blank timeframe -> 0 (no tolerance — forces classify_zone() to
    fall back to "unknown" rather than guessing a window)."""
    seconds_per_candle = TIMEFRAME_SECONDS.get(timeframe.upper(), 0) if timeframe else 0
    return seconds_per_candle * window


def _safe_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _structure_coverage_range(swing_points: List[SwingPoint]) -> Optional[Tuple[int, int]]:
    """Fix #5C correction — the (earliest, latest) timestamp that structure
    evidence (swing_points) actually spans. None when there's no resolvable
    evidence at all (empty swing_points, or none have a parsable timestamp).
    A zone outside this range — padded by the same tolerance margin used
    for reversal matching — has no real structure evidence backing a "not
    near a swing" conclusion; that's an absence of evidence, not evidence
    of absence, so classify_zone() below must not call it continuation."""
    timestamps = [ts for sp in swing_points if (ts := _safe_int(sp.timestamp)) is not None]
    if not timestamps:
        return None
    return min(timestamps), max(timestamps)


def classify_zone(zone: SupplyDemandZone, swing_points: List[SwingPoint], timeframe: str = "") -> str:
    """Fix #5B, corrected — additive location-in-move label: "reversal" /
    "continuation" / "unknown". Read-only: doesn't touch zone detection, the
    zone selector, impulse_strength, or Bias/Strategy/Dashboard. BOS/CHoCH
    deliberately not used here (per Fix #5A's audit — reserved for later).

    reversal: zone.timestamp falls within a timeframe/SWING_WINDOW-derived
    tolerance (see _swing_tolerance_seconds()) of a confirmed swing high
    (supply zone) or swing low (demand zone) in `swing_points` — any HH/LH
    for supply, any LL/HL for demand; the sub-label (higher vs lower) isn't
    relevant here, only "was this a confirmed turning point".
    continuation: zone.pattern is RBR (demand) or DBD (supply) — direction
    held on both sides of the zone candle (Fix #5A) — AND zone.timestamp
    falls within the structure evidence's actual coverage window (see
    _structure_coverage_range(), correction) — AND it is not near any
    matching-direction swing point. A zone whose timestamp predates or
    postdates everything structure evidence examined can never be
    "continuation", no matter its pattern — there's no evidence it isn't
    sitting right next to an unconfirmed swing outside that window.
    unknown: no timestamp, no swing_points, unresolvable timeframe, zone
    timestamp outside structure coverage, or neither rule matches — an
    explicit fallback rather than a guess."""
    if zone.type not in ("demand", "supply"):
        return "unknown"

    zone_ts = _safe_int(zone.timestamp)
    tolerance = _swing_tolerance_seconds(timeframe)

    if zone_ts is not None and tolerance > 0 and swing_points:
        relevant_labels = {"HH", "LH"} if zone.type == "supply" else {"LL", "HL"}
        for sp in swing_points:
            if sp.label not in relevant_labels:
                continue
            sp_ts = _safe_int(sp.timestamp)
            if sp_ts is not None and abs(sp_ts - zone_ts) <= tolerance:
                return "reversal"

    coverage = _structure_coverage_range(swing_points)
    within_coverage = (
        zone_ts is not None
        and coverage is not None
        and (coverage[0] - tolerance) <= zone_ts <= (coverage[1] + tolerance)
    )

    if within_coverage:
        if zone.type == "demand" and zone.pattern == "RBR":
            return "continuation"
        if zone.type == "supply" and zone.pattern == "DBD":
            return "continuation"

    return "unknown"


def classify_zones(zones: List[SupplyDemandZone], swing_points: List[SwingPoint], timeframe: str = "") -> List[SupplyDemandZone]:
    """Batch convenience wrapper — sets .classification on each zone in
    place (via classify_zone()) and returns the same list. Not called from
    DemandEngine.get_zones()/get_context()/get_label() or from Output.py —
    those don't have swing_points available, and wiring this into the live
    output pipeline is a separate step, not part of Fix #5B."""
    for zone in zones:
        zone.classification = classify_zone(zone, swing_points, timeframe)
    return zones


class DemandEngine:
    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine

    def get_zones(self, symbol: str, tf: str, count: int = 50, cache=None) -> List[SupplyDemandZone]:
        candles = self.candle_engine.get_snapshots(symbol, tf, count=count, cache=cache)
        return detect_zones(candles)

    def get_context(self, symbol: str, tf: str, count: int = 50, cache=None, zones: Optional[List[SupplyDemandZone]] = None) -> Tuple[str, Optional[float]]:
        """Canonical context_zone/context_level for a symbol/timeframe —
        see select_active_zone(). get_label() below reuses this so
        DemandEngine has exactly one zone-selection rule, not two.

        Fix #4D3 — optional `zones`: pass an already-computed zone list
        (e.g. from get_zones()) to skip detect_zones() here and reuse it
        instead. Omitted/None (every existing caller) behaves exactly as
        before — detect_zones() runs here same as always."""
        candles = self.candle_engine.get_snapshots(symbol, tf, count=count, cache=cache)
        if not candles:
            return "neutral", None
        if zones is None:
            zones = detect_zones(candles)
        return select_active_zone(zones, candles[-1].close)

    def get_label(self, symbol: str, tf: str, cache=None) -> str:
        zone_type, _ = self.get_context(symbol, tf, cache=cache)
        return zone_type
