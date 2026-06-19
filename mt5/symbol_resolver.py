# symbol_resolver.py

from typing import Optional, List, Dict
from difflib import get_close_matches, SequenceMatcher
import MetaTrader5 as mt5

# ─────────────────────────────────────────────
# 🧠 Internal Cache
_symbol_cache: Dict[str, str] = {}

# ─────────────────────────────────────────────
# 🔧 Initialization
def ensure_mt5_initialized() -> bool:
    if not mt5.initialize():
        print("❌ MT5 initialization failed")
        return False
    return True

# ─────────────────────────────────────────────
# 🔠 Symbol Normalization
def normalize_symbol_case(symbol: str | object) -> str:
    if isinstance(symbol, tuple):
        symbol = symbol[0]
    if hasattr(symbol, "name"):
        symbol = symbol.name
    if not isinstance(symbol, str):
        raise TypeError(f"Expected str, SymbolInfo, or tuple, got {type(symbol)}")

    symbol = symbol.strip()
    for i, char in enumerate(symbol):
        if char.islower() and i > 0:
            return symbol[:i].upper() + symbol[i:].lower()
    return symbol.upper()

# ─────────────────────────────────────────────
# 🎯 Single Symbol Resolver
def resolve_symbol(base: str) -> Optional[str]:
    base = normalize_symbol_case(base)
    if base in _symbol_cache:
        return _symbol_cache[base]

    all_symbols = mt5.symbols_get()
    if not all_symbols:
        return None

    normalized_names = [normalize_symbol_case(s.name) for s in all_symbols]
    matches = get_close_matches(base, normalized_names, n=1, cutoff=0.6)

    if not matches:
        return None

    resolved = next(
        (s.name for s in all_symbols if normalize_symbol_case(s.name) == matches[0]),
        None
    )
    _symbol_cache[base] = resolved
    return resolved

# ─────────────────────────────────────────────
# 🧪 Batch Symbol Resolver
def resolve_symbols_batch(
    clean_list: List[str],
    verbose: bool = False,
    strict: bool = False
) -> Dict[str, Dict]:
    if not ensure_mt5_initialized():
        return {
            "symbol_map": {},
            "unresolved": clean_list,
            "confidence": {},
            "error": "MT5 initialization failed"
        }

    all_symbols = mt5.symbols_get()
    if not all_symbols:
        return {
            "symbol_map": {},
            "unresolved": clean_list,
            "confidence": {},
            "error": "MT5 symbols_get() returned None"
        }

    normalized_names = [normalize_symbol_case(s.name) for s in all_symbols]
    mapping: Dict[str, Optional[str]] = {}
    confidence: Dict[str, float] = {}
    unresolved: List[str] = []

    for base in clean_list:
        base_norm = normalize_symbol_case(base)
        best_match = None
        best_score = 0.0

        for name in normalized_names:
            score = SequenceMatcher(None, base_norm, name).ratio()
            if score > best_score:
                best_score = score
                best_match = name

        resolved = None
        if not strict or best_score >= 0.85:
            resolved = next(
                (s.name for s in all_symbols if normalize_symbol_case(s.name) == best_match),
                None
            )

        mapping[base] = resolved
        confidence[base] = round(best_score, 3)

        if not resolved:
            unresolved.append(base)
            if verbose:
                print(f"❌ {base} not resolved (score: {best_score:.2f})")
        elif verbose:
            print(f"✅ {base} → {resolved} (score: {best_score:.2f})")

    return {
        "symbol_map": mapping,
        "unresolved": unresolved,
        "confidence": confidence
    }
