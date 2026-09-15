"""Fix #7G — canonical `chart_markings` contract (Fix #7F's design).

Purely additive infrastructure: a shared marking type/validator/builder
that future Strategy plugins can attach to their `react()` result via a
new, optional `chart_markings` list. Nothing in this module is wired into
any of the 7 existing strategies, `StrategyEngine`, or `StrategySnapshot`
-- this fix only adds the shared building block described in Fix #7F's
report, so a strategy can emit one or more chart markings without the
dashboard having to re-derive geometry itself.

Supported marking types: zone, level, candle, range, structure, profile,
phase (Fix #7F). Required fields: type, strategy, timeframe, label.
Optional fields (omitted entirely when not given, never filled with
None): direction, price, top, bottom, timestamp, start_timestamp,
end_timestamp, candle_index, start_index, end_index, evidence_ref.

This module defines no Strategy subclass, so
StrategyEngine._discover_strategies() (which auto-loads every .py file in
this package looking for Strategy subclasses) finds nothing here and
silently continues -- no change needed to its _EXCLUDED_MODULES list.
"""
from typing import Any, Dict, Optional

MARKING_TYPES = frozenset({"zone", "level", "candle", "range", "structure", "profile", "phase"})

_REQUIRED_FIELDS = ("type", "strategy", "timeframe", "label")

# Order matches Fix #7F's "optional" list exactly.
_OPTIONAL_FIELD_ORDER = (
    "direction", "price", "top", "bottom",
    "timestamp", "start_timestamp", "end_timestamp",
    "candle_index", "start_index", "end_index",
    "evidence_ref",
)


class ChartMarkingError(ValueError):
    """Raised when a chart marking fails required-field or geometry validation."""


def _validate_geometry(marking: Dict[str, Any]) -> None:
    """Type-specific geometry rules (Fix #7F/#7G). Assumes `marking["type"]`
    is already known to be one of MARKING_TYPES -- validate_chart_marking()
    checks that before calling this."""
    marking_type = marking["type"]

    if marking_type == "zone":
        if marking.get("top") is None or marking.get("bottom") is None:
            raise ChartMarkingError("zone marking requires both 'top' and 'bottom'")

    elif marking_type == "level":
        if marking.get("price") is None:
            raise ChartMarkingError("level marking requires 'price'")

    elif marking_type == "candle":
        if marking.get("timestamp") is None and marking.get("candle_index") is None:
            raise ChartMarkingError("candle marking requires 'timestamp' or 'candle_index'")

    elif marking_type in ("range", "phase"):
        ts_start, ts_end = marking.get("start_timestamp"), marking.get("end_timestamp")
        idx_start, idx_end = marking.get("start_index"), marking.get("end_index")
        # Each pair must be either fully present or fully absent -- no
        # dangling half-pair (a start with no end, or vice versa).
        ts_pair_ok = (ts_start is None) == (ts_end is None)
        idx_pair_ok = (idx_start is None) == (idx_end is None)
        has_any_complete_pair = (
            (ts_start is not None and ts_end is not None)
            or (idx_start is not None and idx_end is not None)
        )
        if not (ts_pair_ok and idx_pair_ok and has_any_complete_pair):
            raise ChartMarkingError(
                f"{marking_type} marking requires a complete start/end pair "
                "(start_timestamp+end_timestamp and/or start_index+end_index, "
                "never just one side of a pair)"
            )

    elif marking_type == "structure":
        if (
            marking.get("timestamp") is None
            and marking.get("candle_index") is None
            and marking.get("price") is None
        ):
            raise ChartMarkingError(
                "structure marking requires at least one of 'timestamp', "
                "'candle_index', or 'price'"
            )

    elif marking_type == "profile":
        has_poc = marking.get("price") is not None
        has_value_area = marking.get("top") is not None and marking.get("bottom") is not None
        if not (has_poc or has_value_area):
            raise ChartMarkingError(
                "profile marking requires 'price' (POC) and/or both 'top' "
                "and 'bottom' (value area)"
            )


def validate_chart_marking(marking: Dict[str, Any]) -> None:
    """Raises ChartMarkingError if `marking`:
    - has an unrecognized/missing `type`,
    - is missing any required field (type, strategy, timeframe, label), or
    - fails its type's own geometry requirement.
    Does not mutate `marking`. Safe to call on a hand-built dict, not just
    one produced by make_chart_marking()."""
    marking_type = marking.get("type")
    if marking_type not in MARKING_TYPES:
        raise ChartMarkingError(f"unknown marking type: {marking_type!r}")

    missing_required = [f for f in _REQUIRED_FIELDS if not marking.get(f)]
    if missing_required:
        raise ChartMarkingError(f"chart marking missing required field(s): {missing_required}")

    _validate_geometry(marking)


def make_chart_marking(
    marking_type: str,
    strategy: str,
    timeframe: str,
    label: str,
    *,
    direction: Optional[str] = None,
    price: Optional[float] = None,
    top: Optional[float] = None,
    bottom: Optional[float] = None,
    timestamp: Optional[str] = None,
    start_timestamp: Optional[str] = None,
    end_timestamp: Optional[str] = None,
    candle_index: Optional[int] = None,
    start_index: Optional[int] = None,
    end_index: Optional[int] = None,
    evidence_ref: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Builds and validates one chart marking dict (Fix #7F's contract).

    Optional fields left as their None default are OMITTED from the
    returned dict entirely -- never filled in as an explicit null --
    matching Fix #7F's "only what chart perlukan" requirement.

    Raises ChartMarkingError if the required fields or the marking type's
    own geometry requirement (see validate_chart_marking()) aren't
    satisfied. Raises nothing else; callers get a fully valid dict back
    or an exception, never a partially-built marking.
    """
    marking: Dict[str, Any] = {
        "type": marking_type,
        "strategy": strategy,
        "timeframe": timeframe,
        "label": label,
    }
    optional_values = {
        "direction": direction, "price": price, "top": top, "bottom": bottom,
        "timestamp": timestamp, "start_timestamp": start_timestamp, "end_timestamp": end_timestamp,
        "candle_index": candle_index, "start_index": start_index, "end_index": end_index,
        "evidence_ref": evidence_ref,
    }
    for key in _OPTIONAL_FIELD_ORDER:
        value = optional_values[key]
        if value is not None:
            marking[key] = value

    validate_chart_marking(marking)
    return marking


def add_chart_marking(signal: Dict[str, Any], marking: Dict[str, Any]) -> Dict[str, Any]:
    """Appends an already-built (and already-valid) marking dict onto
    signal["chart_markings"], creating that list if this is the first
    marking on this signal. Returns `signal` for chaining. Purely
    additive: never required, never reads or changes any other key on
    `signal` -- a strategy that never calls this produces byte-identical
    output to before this fix (Fix #7G's own regression guarantee)."""
    signal.setdefault("chart_markings", []).append(marking)
    return signal
