import asyncio
from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel
from typing import List

from core.BiasEngine import BiasEngine
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
from mt5.constants import SYMBOLS

router = APIRouter()

# Instantiate shared engines
candle_engine = CandleEngine()
strength_engine = StrengthEngine()
bias_engine = BiasEngine(candle_engine, strength_engine)
momentum_engine = MomentumEngine(candle_engine)
demand_engine = DemandEngine(candle_engine)
structure_engine = StructureEngine(candle_engine)
shift_engine = ShiftEngine(candle_engine)

@router.get("/symbols")
def get_supported_symbols():
    return {"symbols": SYMBOLS}

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
    engine = StructureEngine(candle_engine)
    snapshots = engine.batch_snapshots(symbols, tf)
    return snapshots


@router.get("/bias/shift", response_model=List[BiasShiftEvent])
def get_bias_shift_events(
    symbols: List[str] = ["XAUUSD_i", "BTCUSD_i", "EURUSD_i"],
    tf: str = "M15",
   
):
    structure_engine = StructureEngine(candle_engine)
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
    structure_engine = StructureEngine(candle_engine)
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
    print(type(candle_engine))                 # <class '...CandleEngine'>
    print(type(shift_engine.candle_engine))    # <class '...CandleEngine'>
    # Build snapshot payload
    result = build_multi_symbol_output(
        bias_engine=bias_engine,
        candle_engine=candle_engine,
        momentum_engine=momentum_engine,
        demand_engine=demand_engine,
        shift_engine=shift_engine,
        structure_engine=structure_engine
    )

    return result

@router.websocket("/output/ws")
async def output_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            result = build_multi_symbol_output(
                bias_engine=bias_engine,
                candle_engine=candle_engine,
                momentum_engine=momentum_engine,
                demand_engine=demand_engine,
                shift_engine=shift_engine,
                structure_engine=structure_engine
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

