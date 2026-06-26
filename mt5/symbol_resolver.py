# symbol_resolver.py

from typing import Optional, List, Dict, Tuple
from difflib import SequenceMatcher
import MetaTrader5 as mt5

from .init import ensure_mt5_ready

# ─────────────────────────────────────────────
# 🧠 Internal Cache
_symbol_cache: Dict[str, str] = {}

DEFAULT_MATCH_CUTOFF = 0.6

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
# 🧩 Shared fuzzy-match core — single source of truth for both resolvers
def _best_match(base_norm: str, normalized_names: List[str]) -> Tuple[Optional[str], float]:
    best_match = None
    best_score = 0.0
    for name in normalized_names:
        score = SequenceMatcher(None, base_norm, name).ratio()
        if score > best_score:
            best_score = score
            best_match = name
    return best_match, best_score

# ─────────────────────────────────────────────
# 🎯 Single Symbol Resolver
def resolve_symbol(base: str, cutoff: float = DEFAULT_MATCH_CUTOFF) -> Optional[str]:
    base_norm = normalize_symbol_case(base)
    if base_norm in _symbol_cache:
        return _symbol_cache[base_norm]

    all_symbols = mt5.symbols_get()
    if not all_symbols:
        return None

    normalized_names = [normalize_symbol_case(s.name) for s in all_symbols]
    best_match, best_score = _best_match(base_norm, normalized_names)

    if best_match is None or best_score < cutoff:
        return None

    resolved = next(
        (s.name for s in all_symbols if normalize_symbol_case(s.name) == best_match),
        None
    )
    _symbol_cache[base_norm] = resolved
    return resolved

# ─────────────────────────────────────────────
# 🧪 Batch Symbol Resolver
def resolve_symbols_batch(
    clean_list: List[str],
    verbose: bool = False,
    strict: bool = False
) -> Dict[str, Dict]:
    try:
        ensure_mt5_ready()
    except RuntimeError as e:
        return {
            "symbol_map": {},
            "unresolved": clean_list,
            "confidence": {},
            "error": str(e)
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

    cutoff = 0.85 if strict else DEFAULT_MATCH_CUTOFF

    for base in clean_list:
        base_norm = normalize_symbol_case(base)
        best_match, best_score = _best_match(base_norm, normalized_names)

        resolved = None
        if best_match is not None and best_score >= cutoff:
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
