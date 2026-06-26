import asyncio
import random
import time
from typing import Optional, Dict
from fastapi import APIRouter, Query, WebSocket
from pydantic import BaseModel
import MetaTrader5 as mt5

from mt5.constants import SYMBOLS
from mt5.init import ensure_mt5_ready
from mt5.symbol_resolver import normalize_symbol_case, resolve_symbol, resolve_symbols_batch
from mt5.mt5_diagnostics import tag_usability

router = APIRouter()

# 🔧 Timeframe mapping
TF_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1
}


@router.get("/mt5/candle-status")
def candle_status(timeframe: str = Query("M1"), count: int = Query(10)):
    tf = TF_MAP.get(timeframe.upper())
    if tf is None:
        return {"status": "error", "message": f"Invalid timeframe: {timeframe}"}

    try:
        ensure_mt5_ready()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    # 🔍 Resolve symbols
    resolution = resolve_symbols_batch(SYMBOLS, verbose=False, strict=False)
    symbol_map = resolution["symbol_map"]
    confidence = resolution["confidence"]
    unresolved = resolution["unresolved"]

    diagnostics: Dict[str, Dict] = {}
    working, missing = [], []

    for base, resolved in symbol_map.items():
        if not resolved:
            diagnostics[base] = {
                "resolved": None,
                "confidence": confidence.get(base),
                "candle_status": "unresolved"
            }
            continue

        # Ensure symbol is selected
        mt5.symbol_select(resolved, True)

        try:
            candles = mt5.copy_rates_from_pos(resolved, tf, 0, count)
        except Exception as e:
            candles = None

        if candles is None or len(candles) == 0:
            missing.append(base)
            diagnostics[base] = {
                "resolved": resolved,
                "confidence": confidence.get(base),
                "candle_status": "missing"
            }
        else:
            working.append(base)
            diagnostics[base] = {
                "resolved": resolved,
                "confidence": confidence.get(base),
                "candle_status": "working",
                "candle_count": len(candles)
            }

    diagnostics = tag_usability(diagnostics)

    return {
        "status": "ok",
        "summary": {
            "total": len(SYMBOLS),
            "resolved": len(SYMBOLS) - len(unresolved),
            "unresolved": len(unresolved),
            "working": len(working),
            "missing": len(missing)
        },
        "diagnostics": diagnostics
    }


class SymbolResponse(BaseModel):
    input: str
    resolved: Optional[str]
    status: str
    visible: Optional[bool] = None
    selected: Optional[bool] = None


@router.get("/mt5/symbol", response_model=SymbolResponse)
def get_symbol_info(symbol: str = Query(..., description="Symbol name to resolve")):
    try:
        ensure_mt5_ready()
    except RuntimeError as e:
        return SymbolResponse(input=symbol, resolved=None, status="error")

    resolved = resolve_symbol(symbol)
    if not resolved:
        return SymbolResponse(input=symbol, resolved=None, status="not_found")

    info = mt5.symbol_info(resolved)
    return SymbolResponse(
        input=symbol,
        resolved=resolved,
        status="ok",
        visible=info.visible if info else None,
        selected=info.selected if info else None
    )

@router.get("/mt5/symbols")
def get_symbols():
    return {"symbols": SYMBOLS}

@router.get("/mt5/symbols-debug")
def debug_symbols():
    try:
        ensure_mt5_ready()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    symbols = mt5.symbols_get()
    if not symbols:
        return {"status": "error", "message": "No symbols returned"}

    return {
        "status": "ok",
        "count": len(symbols),
        "sample": [s.name for s in symbols[:10]]
    }


@router.get("/mt5/resolve")
def resolve_symbol_endpoint(base: str = Query(..., description="Base symbol like XAUUSD")):
    if not base or base.strip() == "":
        return {"status": "error", "message": "No base symbol provided"}

    base_norm = normalize_symbol_case(base)

    # ✅ First try direct match against your whitelist
    for s in SYMBOLS:
        if normalize_symbol_case(s).startswith(base_norm):
            return {"status": "ok", "resolved": s}

    # 🔄 Fallback to MT5 fuzzy resolver
    resolved: Optional[str] = resolve_symbol(base_norm)
    if resolved:
        return {"status": "ok", "resolved": resolved}

    return {"status": "error", "message": f"Could not resolve {base}"}


@router.get("/mt5/history")
def get_history(symbol: str = "XAUUSD_i", timeframe: int = mt5.TIMEFRAME_M1, bars: int = 500):
    ensure_mt5_ready()

    info = mt5.symbol_info(symbol)
    if info is None:
        return {"error": f"Symbol {symbol} not found in MT5"}
    if not info.visible:
        mt5.symbol_select(symbol, True)

    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None:
        return {"error": f"No rates returned for {symbol} {timeframe}, last_error={mt5.last_error()}"}

    candles = [
        {
            "time": int(r["time"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        for r in rates
    ]
    return candles


@router.websocket("/ws/ticks")
async def ws_ticks(ws: WebSocket):
    await ws.accept()
    symbol = ws.query_params.get("symbol") or "XAUUSD"  # fallback
    print(f"[WS] Client connected for {symbol}")

    try:
        ensure_mt5_ready()
    except RuntimeError as e:
        await ws.send_json({"error": str(e)})
        await ws.close()
        return

    # Ensure symbol is visible
    if not mt5.symbol_select(symbol, True):
        err = f"Symbol {symbol} not visible/available"
        print(f"[WS] {err}")
        await ws.send_json({"error": err})
        await ws.close()
        return

    try:
        while True:
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                price = tick.last or tick.bid or tick.ask
                print(f"[WS] sending {symbol} price={price}")
                await ws.send_json({
                    "time": int(tick.time),  # seconds
                    "last": tick.last,
                    "bid": tick.bid,
                    "ask": tick.ask,
                })
            else:
                # Explicitly surface the issue; no silent loops
                print(f"[WS] no tick for {symbol}")
            await asyncio.sleep(0.5)
    except Exception as e:
        print(f"[WS] closed for {symbol}: {e}")