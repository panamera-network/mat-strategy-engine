from typing import Dict, Optional
from core.strategy.strategy_models import Strategy, StrategySnapshot


class ScalpingBiasCascade(Strategy):
    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        scalping_tfs = ["M1", "M5", "M15", "M30"]
        swing_tfs = ["H1", "H4"] # reserved for future use

        if snapshot.timeframe not in scalping_tfs:
            return None

        symbol = snapshot.symbol

        # Check alignment across scalping + swing timeframes
        alignment_tfs = ["M15", "M30", "H1"]  # exclude M5 from context
        aligned = (
            snapshot.bias == "Bullish" and
            all(
                context.get(f"{symbol}_{tf}") and context[f"{symbol}_{tf}"].bias == "Bullish"
                for tf in alignment_tfs
            )
        )



        # Check early shift: M1 confirms bearish bias, M5 shows CHOCH
        m1 = context.get(f"{symbol}_M1")

        if aligned and m1 and m1.bias == "Bearish" and not m1.suppression and snapshot.structure_type == "CHOCH":
            return {
                "symbol": symbol,
                "timeframe": snapshot.timeframe,
                "direction": "short",
                "reason": "Scalping bias cascade",
                "confidence": snapshot.momentum,
                "trigger": snapshot.structure_type,
                "timestamp": snapshot.timestamp
            }
        
        if not aligned:
            print("[Cascade] Alignment failed")
        elif not m1:
            print("[Cascade] M1 snapshot missing")
        elif m1.bias != "Bearish":
            print("[Cascade] M1 bias not bearish")
        elif m1.suppression:
            print("[Cascade] M1 is suppressed")
        elif snapshot.structure_type != "CHOCH":
            print("[Cascade] Snapshot structure not CHOCH")

        print(f"[Cascade] Snapshot TF: {snapshot.timeframe}, Bias: {snapshot.bias}, Structure: {snapshot.structure_type}")
        print(f"[Cascade] M1 Bias: {m1.bias if m1 else 'None'}, Suppression: {m1.suppression if m1 else 'None'}")
        print(f"[Cascade] Alignment: {aligned}")

        return None


