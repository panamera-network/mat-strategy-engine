import MetaTrader5 as mt5

def initialize_mt5() -> bool:
    """Initialize MetaTrader 5 connection."""
    if not mt5.initialize():
        print("❌ MT5 initialization failed:", mt5.last_error())
        return False
    return True
