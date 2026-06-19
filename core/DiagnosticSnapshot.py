# core/DiagnosticSnapshot.py

from core.BiasEngine import BiasEngine
from core.CandleEngine import CandleEngine
from core.MomentumEngine import MomentumEngine
from core.StrengthEngine import StrengthEngine
from core.StructureEngine import get_structure_snapshot
from core.SuppressionEngine import get_suppression_reasons
from core.core_models import (
    Candle, Context,
    DiagnosticSnapshot
)
from core.log import log_error

def build_diagnostic_snapshot(
    candle: Candle,
    context: Context,
    bias_engine,
    strength_engine,
    momentum_engine
) -> DiagnosticSnapshot | None:
    try:
        # 🧠 Hydrate Components
        bias = bias_engine.get_bias_snapshot(candle, context)
        momentum = momentum_engine.get_momentum_snapshot(candle, context)
        strength = strength_engine.get_strength_snapshot(candle, context)
        structure = get_structure_snapshot(candle.symbol, candle.timeframe)
        suppression = get_suppression_reasons(bias) + get_suppression_reasons(momentum)
        confidence = round((bias.strength + momentum.momentum + structure.label_weight) / 3, 2)
        status = "active", "suppressed", "conflicted"

        # 🧪 Validate
        if not all([bias, momentum, structure]):
            return None

        # 🧠 Build Diagnostic Snapshot
        return DiagnosticSnapshot(
            candle=candle,
            context=context,
            bias=bias,
            momentum=momentum,
            structure=structure,
            strength=strength,
            suppression=suppression,
            confidence=confidence,
            status=status
        )
    except Exception as e:
        # Optional: log error upstream
        print(f"[Snapshot Error] {candle.symbol} {candle.timeframe} → {e}")
        return None


def get_diagnostics(
    symbols: list[str],
    timeframes: list[str],
    candle_engine: CandleEngine,
    bias_engine: BiasEngine,
    strength_engine: StrengthEngine,
    momentum_engine: MomentumEngine
) -> dict[str, dict[str, DiagnosticSnapshot]]:
    diagnostics = {}
    for symbol in symbols:
        diagnostics[symbol] = {}
        for tf in timeframes:
            candles = candle_engine.get_snapshots(symbol, tf, count=6)
            if not candles:
                continue
            candle = candles[-1]
            context = Context(symbol=symbol, timeframe=tf)
            snapshot = build_diagnostic_snapshot(
                candle=candle,
                context=context,
                bias_engine=bias_engine,
                strength_engine=strength_engine,
                momentum_engine=momentum_engine
            )
            if snapshot:
                diagnostics[symbol][tf] = snapshot
    return diagnostics
