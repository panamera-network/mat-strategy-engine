from typing import Dict, List
import MetaTrader5 as mt5


def check_connection() -> Dict:
    if not mt5.initialize():
        return {"status": "error", "message": f"MT5 initialization failed: {mt5.last_error()}"}
    return {"status": "ok", "message": "MT5 initialized and ready"}


def validate_symbol(symbol: str) -> Dict:
    if not mt5.symbol_select(symbol, True):
        return {"status": "error", "message": f"Symbol '{symbol}' not available"}
    info = mt5.symbol_info(symbol)
    if info is None:
        return {"status": "error", "message": f"No info for symbol '{symbol}'"}
    return {"status": "ok", "message": f"Symbol '{symbol}' is valid", "details": info._asdict()}


def test_data_fetch(symbol: str, timeframe: int, count: int) -> Dict:
    try:
        data = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if data is None or len(data) == 0:
            return {"status": "error", "message": "No data returned"}
        return {"status": "ok", "message": f"Fetched {len(data)} candles", "candle_count": len(data)}
    except Exception as e:
        return {"status": "error", "message": f"Exception during fetch: {e}"}


def hybrid_diagnose(symbol: str, timeframe: int = mt5.TIMEFRAME_M1, count: int = 200) -> Dict:
    connection = check_connection()
    symbol_check = validate_symbol(symbol)
    data_check = test_data_fetch(symbol, timeframe, count)

    usable = (
        connection["status"] == "ok" and
        symbol_check["status"] == "ok" and
        data_check["status"] == "ok"
    )

    return {
        "symbol": symbol,
        "connection": connection,
        "symbol_check": symbol_check,
        "data_check": data_check,
        "usable": usable
    }


def run_batch_hybrid(symbols: List[str], timeframe: int = mt5.TIMEFRAME_M1, count: int = 200) -> Dict[str, Dict]:
    results = {}
    for symbol in symbols:
        results[symbol] = hybrid_diagnose(symbol, timeframe, count)
    return results

def tag_usability(diagnostics: Dict[str, Dict]) -> Dict[str, Dict]:
    for symbol, diag in diagnostics.items():
        diag["usable"] = bool(
            diag.get("resolved") and diag.get("candle_status") == "working"
        )
    return diagnostics

def log_unusable_symbols(diagnostics: Dict[str, Dict]):
    for symbol, diag in diagnostics.items():
        if not diag.get("usable"):
            print(f"⚠️ Unusable: {symbol} → {diag['data_check'].get('message')}")


def log_to_file(diagnostics: Dict[str, Dict], path: str = "mt5_diagnostics.log"):
    with open(path, "w") as f:
        for symbol, diag in diagnostics.items():
            f.write(f"{symbol}: {diag}\n")
