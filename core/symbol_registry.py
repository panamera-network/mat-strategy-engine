# symbol_registry.py

from typing import List, Dict, Set

from mt5.constants import SYMBOLS
from mt5.symbol_resolver import resolve_symbols_batch


class SymbolRegistry:
    def __init__(self, raw_symbols: List[str], strict: bool = True, verbose: bool = False):
        self.raw_symbols = raw_symbols
        self.strict = strict
        self.verbose = verbose
        self.symbol_map: Dict[str, str] = {}
        self.unresolved: List[str] = []
        self.confidence: Dict[str, float] = {}
        self.valid_symbols: Set[str] = set()

        self._resolve()

    def _resolve(self):
        result = resolve_symbols_batch(
            clean_list=self.raw_symbols,
            strict=self.strict,
            verbose=self.verbose
        )
        self.symbol_map = result["symbol_map"]
        self.unresolved = result["unresolved"]
        self.confidence = result["confidence"]
        self.valid_symbols = set(filter(None, self.symbol_map.values()))

    def is_valid(self, symbol: str) -> bool:
        return symbol.upper().strip() in self.valid_symbols

    def get_all(self) -> List[str]:
        return sorted(self.valid_symbols)

    def get_confidence(self, symbol: str) -> float:
        return self.confidence.get(symbol, 0.0)

    def get_unresolved(self) -> List[str]:
        return self.unresolved


