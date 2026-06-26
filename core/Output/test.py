"""Manual debug script for build_multi_symbol_output(). Not an automated test —
run directly to eyeball the JSON output. Requires a live MT5 connection."""
import json
import logging
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.BiasEngine import BiasEngine
from core.CandleEngine import CandleEngine
from core.MomentumEngine import MomentumEngine
from core.Output.Output import build_multi_symbol_output
from core.ShiftEngine import ShiftEngine
from core.StrengthEngine import StrengthEngine
from core.StructureEngine import StructureEngine
from core.demand_engine import DemandEngine

logging.basicConfig(level=logging.INFO)

candle_engine = CandleEngine()
strength_engine = StrengthEngine()
bias_engine = BiasEngine(candle_engine, strength_engine)
momentum_engine = MomentumEngine(candle_engine)
demand_engine = DemandEngine(candle_engine)
structure_engine = StructureEngine(candle_engine)
shift_engine = ShiftEngine(candle_engine)


def run():
    result = build_multi_symbol_output(
        bias_engine, candle_engine, momentum_engine,
        demand_engine, structure_engine, shift_engine
    )

    print("\n=== All symbols ===")
    print(json.dumps(result, indent=2))

    target = "ETHUSD_i"
    print(f"\n=== Single symbol ({target}) ===")
    print(json.dumps(result.get(target, {"error": "symbol not found"}), indent=2))


if __name__ == "__main__":
    run()
