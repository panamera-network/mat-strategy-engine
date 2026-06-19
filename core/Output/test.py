import sys
import os
import json
import logging

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.BiasEngine import BiasEngine
from core.CandleEngine import CandleEngine
from core.MomentumEngine import MomentumEngine
from core.output.safe_build_and_serialize import safe_build_and_serialize  # adjust case if needed
from core.ShiftEngine import ShiftEngine
from core.StrengthEngine import StrengthEngine
from core.StructureEngine import StructureEngine
from core.demand_engine import DemandEngine
from core.strategy.StrategyEngine import StrategyEngine

# Configure logging
logging.basicConfig(level=logging.INFO)

# Instantiate shared engines
candle_engine = CandleEngine()
strength_engine = StrengthEngine()
bias_engine = BiasEngine(candle_engine, strength_engine)
momentum_engine = MomentumEngine(candle_engine)
demand_engine = DemandEngine(candle_engine)
structure_engine = StructureEngine(candle_engine)  # fixed here
strategy_engine = StrategyEngine()
shift_engine = ShiftEngine(candle_engine)

def run_tests():
    print("\n=== TEST 1: All Symbols ===")
    json_payload_all = safe_build_and_serialize(
        bias_engine, candle_engine, momentum_engine,
        demand_engine, structure_engine, shift_engine
    )
    print("RAW JSON (all symbols):")
    print(json_payload_all)
    parsed_all = json.loads(json_payload_all)
    print("PARSED PYTHON OBJECT (all symbols):")
    print(parsed_all)

    print("\n=== TEST 2: Single Symbol (ETHUSD_i) ===")
    json_payload_single = safe_build_and_serialize(
        bias_engine, candle_engine, momentum_engine,
        demand_engine, structure_engine, shift_engine,
        symbol="ETHUSD_i"
    )
    print("RAW JSON (ETHUSD_i):")
    print(json_payload_single)
    parsed_single = json.loads(json_payload_single)
    print("PARSED PYTHON OBJECT (ETHUSD_i):")
    print(parsed_single)

    print("\n=== TEST 3: Missing Symbol (FAKE_SYMBOL) ===")
    json_payload_missing = safe_build_and_serialize(
        bias_engine, candle_engine, momentum_engine,
        demand_engine, structure_engine, shift_engine,
        symbol="FAKE_SYMBOL"
    )
    print("RAW JSON (FAKE_SYMBOL):")
    print(json_payload_missing)
    parsed_missing = json.loads(json_payload_missing)
    print("PARSED PYTHON OBJECT (FAKE_SYMBOL):")
    print(parsed_missing)

if __name__ == "__main__":
    run_tests()
