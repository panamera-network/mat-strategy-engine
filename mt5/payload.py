# 🏗️ Build payload from MT5

from typing import List

from bias.bias_map import BiasRequest, refine_bias_map
from mt5.fetcher import fetch_candles
from mt5.symbol_resolver import resolve_symbol
from mt5.timeframes import TimeframeData


def build_payload_from_mt5(symbols: List[str], timeframes: List[str], mode: str) -> BiasRequest:
    data = {}
    for symbol in symbols:
        resolved = resolve_symbol(symbol)
        for tf in timeframes:
            candles = fetch_candles(symbol=resolved, timeframe=tf, count=100)
            bias_info = refine_bias_map(candles)
            key = f"{resolved}_{tf}"
            data[key] = TimeframeData(**bias_info)
    return BiasRequest(mode=mode, data=data)

