
from engine.core_models import DiagnosticSnapshot, MomentumPoint, StructureSnapshot
from engine.detect_zone import detect_bos_or_choch
from engine.momentum_engine import analyze_momentum




def build_diagnostic_snapshot(
    structure: StructureSnapshot,
    momentum_points: list[MomentumPoint]
) -> DiagnosticSnapshot:
    
    zone = structure.prev_zone
    structure_signal = detect_bos_or_choch(structure)
    momentum_snapshot = analyze_momentum(momentum_points)

    return DiagnosticSnapshot(
        symbol=structure.symbol,
        timeframe=structure.timeframe,
        zone=zone,
        structure_signal=structure_signal,
        momentum=momentum_snapshot.momentum,
        direction=momentum_snapshot.direction,
        divergence=momentum_snapshot.divergence,
        confidence_drop=momentum_snapshot.confidence_drop
    )


