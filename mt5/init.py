import MetaTrader5 as mt5


def ensure_mt5_ready() -> None:
    """Initialize MT5 and confirm it's actually connected to an account.

    Raises RuntimeError on failure instead of returning a bool — callers that
    need a non-raising check should catch RuntimeError themselves.
    """
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
    if mt5.account_info() is None:
        raise RuntimeError("MT5 initialized but not connected to any account")
