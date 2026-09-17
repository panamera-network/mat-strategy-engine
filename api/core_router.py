import asyncio
from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel
from typing import List, Optional

from core.BiasEngine import BiasEngine
from core.candle_cache import CandleCache
from core.CandleEngine import CandleEngine
from core.ManualRangeVolumeProfile import build_manual_range_marking, build_manual_range_profile
from core.MomentumEngine import MomentumEngine

from core.Output.Output import build_multi_symbol_output

from core.ShiftEngine import ShiftEngine
from core.StrengthEngine import StrengthEngine
from core.StructureEngine import StructureEngine
from core.StyleEngine import build_multi_symbol_snapshot
from core.core_models import BiasShiftEvent, StructureSnapshot
from core.demand_engine import DemandEngine
from core.strategy.StrategyEngine import strategy_engine
from core.strategy.strategy_models import StrategySnapshot
from mt5.constants import SYMBOLS, TIMEFRAMES

router = APIRouter()

# Instantiate shared engines
candle_engine = CandleEngine()
strength_engine = StrengthEngine()
demand_engine = DemandEngine(candle_engine)
# demand_engine injected so StructureEngine resolves context_zone/context_level
# through the same canonical DemandEngine.get_context() every other caller
# uses, instead of detecting SND independently (the old detect_snd()
# heuristic this replaced has been removed entirely — see Fix #4C/#4E1).
structure_engine = StructureEngine(candle_engine, demand_engine=demand_engine)
# structure_engine injected so BiasEngine resolves BOS/CHoCH through the same
# StructureEngine.get_snapshot() every other caller uses, even when a caller
# doesn't explicitly hand in a structure_snapshot/structure_map (see
# BiasEngine._resolve_structure()) — no independent detection either way.
bias_engine = BiasEngine(candle_engine, strength_engine, structure_engine=structure_engine)
momentum_engine = MomentumEngine(candle_engine)
shift_engine = ShiftEngine(candle_engine)
# Fix #6BQ — dedicated ShiftEngine instance for GET /core/diagnostics/style/
# snapshots only. Fix #6BP's audit proved the canonical `shift_engine`
# singleton's current_shift_direction/last_shift_change bookkeeping is
# shared per (symbol, tf) regardless of which route calls into it -- an
# uncached call through this diagnostics route could alter the `duration`
# canonical /core/output and /core/slim later report for the same pair.
# A separate, persistent singleton (not a fresh per-request instance) gives
# this route its own independent duration continuity across calls without
# ever touching the canonical instance's state.
diagnostics_shift_engine = ShiftEngine(candle_engine)

@router.get("/symbols")
def get_supported_symbols():
    return {"symbols": SYMBOLS}


@router.get("/history/{symbol}/{timeframe}")
def get_symbol_history(symbol: str, timeframe: str, count: int = 200):
    """OHLCV history for a single symbol/timeframe — for charting.
    Distinct from /api/mt5/history (routes/mt5_status.py): same underlying
    MT5 data, but goes through CandleEngine like the rest of /core, and
    returns a {symbol, timeframe, candles} envelope instead of a bare list."""
    candles = candle_engine.get_snapshots(symbol, timeframe, count=count)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": [
            {
                "time": int(c.timestamp),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ],
    }


class ManualRangeVolumeProfileRequest(BaseModel):
    symbol: str
    timeframe: str
    # Fix #7Z (stable Manual Range identity follow-up) — timestamps are
    # the CANONICAL, preferred identity: they identify the exact candles
    # selected and remain stable when new candles arrive. Prefer these.
    start_timestamp: Optional[int] = None
    end_timestamp: Optional[int] = None
    # start_index/end_index are accepted ONLY alongside
    # reference_end_timestamp (a stable anchor) -- a naked index pair is
    # rejected by build_manual_range_profile() itself, because its
    # meaning would silently drift as new candles close (this fix's own
    # audit finding/fix). See core/ManualRangeVolumeProfile.py's own
    # module docstring for the full live-verified stability proof.
    start_index: Optional[int] = None
    end_index: Optional[int] = None
    reference_end_timestamp: Optional[int] = None


@router.post("/volume-profile/manual")
def get_manual_range_volume_profile(body: ManualRangeVolumeProfileRequest):
    """Fix #7Z — Manual Range Volume Profile: an explicit, user-triggered
    analysis operation, never evaluated on a market cycle and never
    auto-discovered by StrategyEngine (see core/ManualRangeVolumeProfile.py's
    own module docstring for the full architecture audit). No profile
    exists until this endpoint is called with a real user-selected range.

    PREFER (start_timestamp, end_timestamp) -- raw epoch seconds in this
    account's own broker-server-time reference, the same values already
    returned by each candle's own `time` field from
    GET /core/history/{symbol}/{timeframe}, so a UI that already rendered
    a chart via that endpoint can pass its own candle timestamps straight
    through here without any conversion. These identify the exact
    candles selected and remain stable forever, including across newly
    closed candles.

    (start_index, end_index) is also accepted, but ONLY together with
    `reference_end_timestamp` (the stable anchor those indices are
    relative to, e.g. the same /core/history response's own latest
    candle timestamp) -- a naked index pair with no anchor is rejected
    with confirmed=False, since its meaning would otherwise silently
    drift as new candles close.

    Returns confirmed=False with a human-readable `error` for an invalid
    range (start > end, empty range, unresolvable symbol/timeframe, or a
    naked index request) instead of raising -- a 200 response either
    way, since this is a routine "no data for that selection" outcome,
    not a server error."""
    result = build_manual_range_profile(
        candle_engine,
        body.symbol,
        body.timeframe,
        start_timestamp=body.start_timestamp,
        end_timestamp=body.end_timestamp,
        start_index=body.start_index,
        end_index=body.end_index,
        reference_end_timestamp=body.reference_end_timestamp,
    )
    marking = build_manual_range_marking(result)
    return {**result, "chart_marking": marking}


@router.get("/diagnostics/bias")
def get_bias_diagnostics(symbol: str, timeframes: List[str] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]):
    bias_map = bias_engine.get_bias_map(symbol, timeframes)
    return {"bias": bias_map}

@router.get("/diagnostics/bias/all")
def get_all_bias_diagnostics(timeframes: List[str] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]):
    result = {}
    for symbol in SYMBOLS:
        bias_map = bias_engine.get_bias_map(symbol, timeframes)
        result[symbol] = {"bias": bias_map}
    return {"symbols": result}


@router.get("/structure/snapshots", response_model=List[StructureSnapshot])
def get_structure_snapshots(
    symbols: List[str] = ["XAUUSD_i", "BTCUSD_i", "EURUSD_i"],
    tf: str = "M15", 
):
    engine = StructureEngine(candle_engine, demand_engine=demand_engine)
    snapshots = engine.batch_snapshots(symbols, tf)
    return snapshots


@router.get("/bias/shift", response_model=List[BiasShiftEvent])
def get_bias_shift_events(
    symbols: List[str] = ["XAUUSD_i", "BTCUSD_i", "EURUSD_i"],
    tf: str = "M15",
):
    """Fix #6BK — retired. Fix #6BJ's audit found detect_bias_shift() never
    actually detected a shift (its `prev_bias` argument was hardcoded and
    never compared against anything) -- every call just re-reported
    whatever structural event happened to be currently confirmed, with no
    dedup. The real, canonical fact (a confirmed structural event) is
    already exposed via /core/output's structure_events block, cached and
    batched. Route, query signature, and response schema are kept for
    backward compatibility; always returns an empty list now, with no
    StructureEngine instantiation or candle fetch."""
    return []


@router.get("/bias/shift/multi", response_model=List[BiasShiftEvent])
def get_multi_tf_bias_shift_events(
    symbols: List[str] = ["XAUUSD_i", "BTCUSD_i", "EURUSD_i"],
    timeframes: List[str] = ["M15", "H1", "H4"],
):
    """Fix #6BK — retired, see get_bias_shift_events() above."""
    return []

@router.get("/diagnostics/style/snapshots")
def get_style_snapshots():
    """Fix #6BQ — retrofitted with a request-scoped CandleCache (same
    pattern as /core/output) so the full 36x9 sweep reuses one batch fetch
    per (symbol, tf) instead of every engine call hitting MT5
    independently, and switched to the dedicated `diagnostics_shift_engine`
    instance so this route can no longer alter canonical /core/output's or
    /core/slim's `duration` for any (symbol, tf) pair (Fix #6BP's audit).
    Response shape, route path, and input behavior are unchanged -- no
    normalization retrofit, no new presentation fields."""
    cache = CandleCache(candle_engine)
    cache.fetch_all(SYMBOLS, TIMEFRAMES, count=100)

    result = build_multi_symbol_snapshot(
        bias_engine=bias_engine,
        candle_engine=candle_engine,
        momentum_engine=momentum_engine,
        demand_engine=demand_engine,
        shift_engine=diagnostics_shift_engine,
        structure_engine=structure_engine,
        cache=cache
    )

    return result

@router.get("/output")
def get_output_snapshots():
    # Request-scoped candle cache — one batch fetch per symbol/timeframe,
    # every engine below reads from it instead of hitting MT5 again.
    cache = CandleCache(candle_engine)
    cache.fetch_all(SYMBOLS, TIMEFRAMES, count=100)

    result = build_multi_symbol_output(
        bias_engine=bias_engine,
        candle_engine=candle_engine,
        momentum_engine=momentum_engine,
        demand_engine=demand_engine,
        shift_engine=shift_engine,
        structure_engine=structure_engine,
        cache=cache,
    )

    return result


class OutputRequest(BaseModel):
    symbols: Optional[List[str]] = None


@router.post("/output")
def get_output_snapshots_filtered(body: OutputRequest = OutputRequest()):
    """Same as GET /output, but only processes the given symbols (much
    faster for a small selection — see CandleCache). Empty/omitted list
    falls back to processing every symbol, same as the GET route."""
    target_symbols = body.symbols if body.symbols else SYMBOLS

    cache = CandleCache(candle_engine)
    cache.fetch_all(target_symbols, TIMEFRAMES, count=100)

    result = build_multi_symbol_output(
        bias_engine=bias_engine,
        candle_engine=candle_engine,
        momentum_engine=momentum_engine,
        demand_engine=demand_engine,
        shift_engine=shift_engine,
        structure_engine=structure_engine,
        cache=cache,
        symbols=target_symbols,
    )

    return result

def _slim_symbol_block(block: dict) -> dict:
    """Project a full symbol output block down to the slim contract:
    bias per TF (label/score/strength only), signal_health, the two
    alignment signals, and the SMC maps."""
    if "error" in block:
        return block

    bias = {
        tf: {k: v for k, v in tf_data.items() if k in ("label", "score", "strength")}
        for tf, tf_data in block.get("bias", {}).items()
    }

    return {
        "bias": bias,
        "signal_health": block.get("signal_health"),
        "scalping": {"alignment_signal": block.get("scalping", {}).get("alignment_signal")},
        "swing": {"alignment_signal": block.get("swing", {}).get("alignment_signal")},
        "snr_levels": block.get("snr_levels", {}),
        "order_blocks": block.get("order_blocks", {}),
        "fvg": block.get("fvg", {}),
        "supply_demand_zones": block.get("supply_demand_zones", {}),
        "strategy_signals": block.get("strategy_signals", []),
    }


@router.get("/slim/{symbols}")
def get_slim_output(symbols: str):
    """Lightweight per-symbol output for dashboards: same pipeline as
    /output (request-scoped CandleCache, symbol-filtered), but each block
    is trimmed to bias/signal_health/alignment signals + SMC maps.
    `symbols` is comma-separated, e.g. /core/slim/XAUUSD_i,EURUSD_i."""
    target_symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    if not target_symbols:
        raise HTTPException(status_code=400, detail="No symbols given")

    cache = CandleCache(candle_engine)
    cache.fetch_all(target_symbols, TIMEFRAMES, count=100)

    full = build_multi_symbol_output(
        bias_engine=bias_engine,
        candle_engine=candle_engine,
        momentum_engine=momentum_engine,
        demand_engine=demand_engine,
        shift_engine=shift_engine,
        structure_engine=structure_engine,
        cache=cache,
        symbols=target_symbols,
    )

    return {symbol: _slim_symbol_block(block) for symbol, block in full.items()}


@router.websocket("/output/ws")
async def output_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            cache = CandleCache(candle_engine)
            cache.fetch_all(SYMBOLS, TIMEFRAMES, count=100)

            result = build_multi_symbol_output(
                bias_engine=bias_engine,
                candle_engine=candle_engine,
                momentum_engine=momentum_engine,
                demand_engine=demand_engine,
                shift_engine=shift_engine,
                structure_engine=structure_engine,
                cache=cache,
            )
            await websocket.send_json(result)
            await asyncio.sleep(60)  # adjust frequency
    except Exception as e:
        print("WebSocket closed:", e)


class StrategyToggleRequest(BaseModel):
    enabled: bool


@router.get("/strategies")
def list_strategies():
    return {"strategies": strategy_engine.list_strategies()}


@router.patch("/strategies/{name}")
def toggle_strategy(name: str, body: StrategyToggleRequest):
    if not strategy_engine.set_enabled(name, body.enabled):
        raise HTTPException(status_code=404, detail=f"No strategy named '{name}' is loaded")
    return {"name": name, "enabled": body.enabled}


@router.post("/evaluate")
async def evaluate(request: Request):
    payload = await request.json()
    snapshot_data = payload.get("snapshot")
    context_data = payload.get("context", {})

    if not snapshot_data:
        return {"error": "Missing snapshot"}

    snapshot = StrategySnapshot(**snapshot_data)
    context = {k: StrategySnapshot(**v) for k, v in context_data.items()}

    signals = strategy_engine.evaluate(snapshot, context)
    return {"signals": signals}

