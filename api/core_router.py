import asyncio
from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel
from typing import List, Optional

from core.BiasEngine import BiasEngine
from core.candle_cache import CandleCache
from core.CandleEngine import CandleEngine
from core.MomentumEngine import MomentumEngine

from core.Output.Output import build_multi_symbol_output

from core.ShiftEngine import ShiftEngine, detect_bias_shift
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
# uses, instead of detecting SND independently (detect_snd() is legacy now —
# still in structure_utils.py, just no longer called — see Fix #4/#4C).
structure_engine = StructureEngine(candle_engine, demand_engine=demand_engine)
# structure_engine injected so BiasEngine resolves BOS/CHoCH through the same
# StructureEngine.get_snapshot() every other caller uses, even when a caller
# doesn't explicitly hand in a structure_snapshot/structure_map (see
# BiasEngine._resolve_structure()) — no independent detection either way.
bias_engine = BiasEngine(candle_engine, strength_engine, structure_engine=structure_engine)
momentum_engine = MomentumEngine(candle_engine)
shift_engine = ShiftEngine(candle_engine)

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
    structure_engine = StructureEngine(candle_engine, demand_engine=demand_engine)
    events: List[BiasShiftEvent] = []

    for symbol in symbols:
        snapshot: StructureSnapshot = structure_engine.get_snapshot(symbol, tf)
        if not snapshot or not snapshot.structure_valid:
            continue

        event = detect_bias_shift(
            prev_bias="Neutral",  # Replace with actual bias tracking if available
            snapshot=snapshot,
            symbol=symbol
        )

        if event:
            events.append(event)

    return events

@router.get("/bias/shift/multi", response_model=List[BiasShiftEvent])
def get_multi_tf_bias_shift_events(
    symbols: List[str] = ["XAUUSD_i", "BTCUSD_i", "EURUSD_i"],
    timeframes: List[str] = ["M15", "H1", "H4"],
    
):
    structure_engine = StructureEngine(candle_engine, demand_engine=demand_engine)
    events: List[BiasShiftEvent] = []

    for symbol in symbols:
        for tf in timeframes:
            snapshot = structure_engine.get_snapshot(symbol, tf)
            if not snapshot or not snapshot.structure_valid:
                continue
            
            print({
                "symbol": symbol,
                "timeframe": tf,
                "bias": snapshot.bias,
                "structure_type": snapshot.structure_type,
                "structure": getattr(snapshot, "structure", "missing"),
                "structure_valid": snapshot.structure_valid,
                "context_zone": snapshot.context_zone,
                "context_level": snapshot.context_level
            })

            event = detect_bias_shift(prev_bias="Neutral", snapshot=snapshot, symbol=symbol)
            if event:
                print(f"{symbol} @ {tf} → BiasShiftEvent streamed")
                events.append(event)
            else:
                print(f"{symbol} @ {tf} → No event returned")

    return events

@router.get("/diagnostics/style/snapshots")
def get_style_snapshots():
    print(type(candle_engine))                 # <class '...CandleEngine'>
    print(type(shift_engine.candle_engine))    # <class '...CandleEngine'>
    # Build snapshot payload
    result = build_multi_symbol_snapshot(
        bias_engine=bias_engine,
        candle_engine=candle_engine,
        momentum_engine=momentum_engine,
        demand_engine=demand_engine,
        shift_engine=shift_engine,
        structure_engine=structure_engine
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

