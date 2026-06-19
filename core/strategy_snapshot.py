from typing import List, Dict

from core.BiasEngine import label_from_score
from core.SignalTracker import SignalTracker
from core.TrendEngine import detect_trend
from core.bias_mode import get_direction, get_mode
from core.core_models import BiasSnapshot, StrengthDiagnostic
from core.log import log_error



class StrategySnapshotBuilder:
    def __init__(self, bias_engine, signal_tracker: SignalTracker):
        self.bias_engine = bias_engine
        self.signal_tracker = signal_tracker

    def compute_signal_duration(self, symbol: str, tf: str) -> dict:
        try:
            return self.signal_tracker.get_duration(symbol, tf)
        except Exception as e:
            log_error(symbol, tf, "duration_fetch", str(e))
            return {
                "duration": 0,
                "direction": "error",
                "last_close": None,
                "last_open": None,
                "suppressed": True
            }

    def group_by_mode(self, snapshots: List[BiasSnapshot]) -> Dict[str, List[BiasSnapshot]]:
        grouped = {"scalp": [], "swing": []}
        for snap in snapshots:
            mode = get_mode(snap.timeframe)
            if mode in grouped:
                grouped[mode].append(snap)
        return grouped

    def summarize_mode(self, snapshots: List[BiasSnapshot]) -> Dict:
        if not snapshots:
            return {
                "bias": 0,
                "strength": 0,
                "status": "Suppressed",
                "trend": "Unclear",
                "trend_reason": "No data",
                "confidence": 0,
                "suppressed_count": 0,
                "alignment": False
            }

        avg_bias = sum(s.bias for s in snapshots) / len(snapshots)
        avg_strength = sum(s.strength for s in snapshots) / len(snapshots)
        status = "Strong" if avg_bias >= 7 else "Weak" if avg_bias <= -7 else "Neutral"
        if avg_strength < 4:
            status = "Suppressed"

        trend_info = detect_trend(avg_bias, avg_strength)
        aligned = self.all_same_direction([s.bias for s in snapshots])
        confidence = int(avg_strength * 10)
        if not aligned:
            confidence = int(confidence * 0.6)

        suppressed_count = sum(1 for s in snapshots if s.strength < 2)

        return {
            "bias": round(avg_bias, 1),
            "strength": round(avg_strength, 1),
            "status": status,
            "trend": trend_info["trend"],
            "trend_reason": trend_info["reason"],
            "confidence": confidence,
            "suppressed_count": suppressed_count,
            "alignment": aligned
        }

    def all_same_direction(self, biases: List[float]) -> bool:
        directions = [get_direction(b) for b in biases if b != 0]
        return len(set(directions)) == 1 and directions != []

    def hydrate_symbol(self, symbol: str, timeframes: List[str]) -> Dict:
        try:
            bias_map = self.bias_engine.get_bias_map(symbol, timeframes)
            snapshots = []
            for tf in timeframes:
                entry = bias_map.get(tf, {})
                strength = entry.get("strength_diagnostic").strength if entry.get("strength_diagnostic") else 0
                bias = entry.get("bias_score", 0.0)
                label = label_from_score(bias)
                snapshots.append(
                    BiasSnapshot(
                        symbol=symbol,
                        timeframe=tf,
                        bias_score=bias,
                        bias_label=label,
                        strength_diagnostic=StrengthDiagnostic(
                            strength=entry.get("strength_diagnostic", 0.0),
                            avg_body_ratio=entry.get("avg_body_ratio", 0.0),
                            momentum_slope=entry.get("momentum_slope", 0.0)
                        ),
                     
                    )
                    
                )

            grouped = self.group_by_mode(snapshots)
            bias_payload = {
                s.timeframe: {
                    "bias": s.bias,
                    "strength": s.strength,
                    "status": "Suppressed" if s.strength < 2 else "Active",
                    "direction": get_direction(s.bias),
                    "duration": self.compute_signal_duration(symbol, s.timeframe)
                } for s in snapshots
            }

            return {
                "symbol": symbol,
                "bias": bias_payload,
                "scalping": self.summarize_mode(grouped["scalp"]),
                "swing": self.summarize_mode(grouped["swing"]),
                "timeframes_used": [s.timeframe for s in snapshots]
            }

        except Exception as e:
            log_error(symbol, "multi_tf", "hydrate_symbol", str(e))
            return {
                "symbol": symbol,
                "error": str(e)
            }

    def hydrate_all(self, symbols: List[str], timeframes: List[str]) -> Dict[str, Dict]:
        return {
            symbol: self.hydrate_symbol(symbol, timeframes)
            for symbol in symbols
        }
