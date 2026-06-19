from mt5.fetcher import fetch_candles


class DemandEngine:
    def get_label(self, symbol: str, tf: str) -> str:
        candles = fetch_candles(symbol, tf)
        recent = candles[-5:] if len(candles) >= 5 else candles

        up_count = sum(1 for c in recent if c.close > c.open)
        down_count = sum(1 for c in recent if c.close < c.open)

        if up_count > down_count:
            return "demand"
        elif down_count > up_count:
            return "supply"
        return "neutral"