# mt5_connector.py
import MetaTrader5 as mt5

def init_mt5():
    if not mt5.initialize():
        raise RuntimeError("MT5 failed to initialize")
    if mt5.account_info() is None:
        raise RuntimeError("MT5 not connected to any account")

def get_symbols():
    init_mt5()
    return mt5.symbols_get()
