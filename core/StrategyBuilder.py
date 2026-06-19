# strategybuilder.py

# 📦 Imports
from core.BiasEngine import BiasEngine
from core.CandleEngine import CandleEngine
from core.DiagnosticSnapshot import build_diagnostic_snapshot
from core.MomentumEngine import MomentumEngine
from core.core_models import (
    Candle, Context,
    BiasSnapshot, MomentumSnapshot, StructureSnapshot,
    DiagnosticSnapshot, StrategySnapshot
)
from core.log import log_error

# 🧠 Instantiate Engines
bias_engine = BiasEngine()
momentum_engine = MomentumEngine()
candle_engine = CandleEngine()

# 🕯️ Hydrate Candle + Context from Engine
symbol = "ETHUSDT"
timeframe = "15m"

context_candles = candle_engine.get_snapshots(symbol, timeframe, count=6)

context: Context = Context(symbol=symbol, timeframe=timeframe)

# 🧪 Build Snapshot
snapshot: DiagnosticSnapshot | None = build_diagnostic_snapshot(
    candle=context_candles[-1],
    context=context,
    bias_engine=bias_engine,
    momentum_engine=momentum_engine
)

# 🧠 Strategy Builder
class StrategyBuilder:
    def __init__(self, symbol: str = "", timeframe: str = ""):
        self.symbol = symbol
        self.timeframe = timeframe

    def route(self, snapshot: DiagnosticSnapshot, mode: str) -> StrategySnapshot:
        if mode == "scalping":
            return self.build_scalping(snapshot.bias, snapshot.momentum, snapshot.structure)
        elif mode == "swing":
            return self.build_swing(snapshot.bias, snapshot.structure)
        else:
            raise ValueError(f"Unsupported mode: {mode}")

    def build_scalping(self, bias: BiasSnapshot, momentum: MomentumSnapshot, structure: StructureSnapshot) -> StrategySnapshot:
        conviction = self._compute_conviction(bias, momentum, structure)
        reasons = self._gather_reasons(bias, momentum, structure)
        suppressed = self._check_suppression(momentum)
        return StrategySnapshot(
            mode="scalping",
            conviction=conviction,
            reasons=reasons,
            suppressed=suppressed
        )

    def build_swing(self, bias: BiasSnapshot, structure: StructureSnapshot) -> StrategySnapshot:
        conviction = self._compute_conviction(bias, structure)
        reasons = self._gather_reasons(bias, None, structure)
        suppressed = self._check_suppression(structure)
        return StrategySnapshot(
            mode="swing",
            conviction=conviction,
            reasons=reasons,
            suppressed=suppressed
        )

    def _compute_conviction(self, *components) -> float:
        weights = [getattr(c, "confidence", 0.0) for c in components if c]
        return round(sum(weights) / len(weights), 3) if weights else 0.0

    def _gather_reasons(self, bias, momentum, structure) -> list[str]:
        reasons = []
        if bias and bias.bias:
            reasons.append(f"Bias: {bias.bias}")
        if momentum and getattr(momentum, "slope", None):
            reasons.append(f"Momentum slope: {momentum.slope}")
        if structure and getattr(structure, "label", None):
            reasons.append(f"Structure: {structure.label}")
        return reasons

    def _check_suppression(self, component) -> bool:
        return getattr(component, "suppressed", False)

# 🚦 Route Strategy
if snapshot:
    builder = StrategyBuilder(
        symbol=snapshot.candle.symbol,
        timeframe=snapshot.candle.timeframe
    )
    scalping_snapshot = builder.route(snapshot, mode="scalping")
    swing_snapshot = builder.route(snapshot, mode="swing")

    print("Scalping:", scalping_snapshot)
    print("Swing:", swing_snapshot)
else:
    symbol = getattr(context_candles[-1], "symbol", "unknown")
    timeframe = getattr(context_candles[-1], "timeframe", "unknown")
    log_error(symbol, timeframe, "strategy routing", "snapshot build failed")
