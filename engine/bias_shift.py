

from engine.detect_zone import detect_choch
from engine.momentum_engine import detect_divergence



def check_trigger(symbol: str, tf: str) -> str:
    triggers = []

    if detect_choch(symbol, tf):
        triggers.append("CHOCH")
    if detect_divergence(symbol, tf, direction="bearish"):
        triggers.append("Bearish Divergence")
    if detect_divergence(symbol, tf, direction="bullish"):
        triggers.append("Bullish Divergence")

    return " + ".join(triggers) if triggers else "None"


    
