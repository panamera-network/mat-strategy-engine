import requests

url = "http://localhost:8000/core/evaluate"  # Adjust if your route is prefixed

payload = {
    "snapshot": {
        "symbol": "XAUUSD_i",
        "timeframe": "M5",
        "bias": "Bullish",
        "momentum": 0.9,
        "strength": 0.8,
        "suppression": False,
        "suppression_reason": "",
        "structure_type": "CHOCH",
        "structure_direction": "Bearish",
        "structure_valid": True,
        "context_zone": "supply",
        "context_level": 1925.0,
        "timestamp": "2025-08-31T02:40:00",
        "is_last_bias_candle": False,
        "engulfing_sequence": None,
        "engulfing_strength": None
    },
    "context": {
        "XAUUSD_i_M1": {
            "symbol": "XAUUSD_i",
            "timeframe": "M1",
            "bias": "Bearish",
            "momentum": 0.7,
            "strength": 0.6,
            "suppression": False,
            "suppression_reason": "",
            "structure_type": "flip",
            "structure_direction": "Bearish",
            "structure_valid": True,
            "context_zone": "supply",
            "context_level": 1926.0,
            "timestamp": "2025-08-31T02:39:00",
            "is_last_bias_candle": False,
            "engulfing_sequence": None,
            "engulfing_strength": None
        },
        "XAUUSD_i_M15": {"symbol": "XAUUSD_i", "timeframe": "M15", "bias": "Bullish", "momentum": 0.9, "strength": 0.8, "suppression": False, "suppression_reason": "", "structure_type": "trend", "structure_direction": "Bullish", "structure_valid": True, "context_zone": "supply", "context_level": 1927.0, "timestamp": "2025-08-31T02:30:00", "is_last_bias_candle": False, "engulfing_sequence": None, "engulfing_strength": None},
        "XAUUSD_i_M30": {"symbol": "XAUUSD_i", "timeframe": "M30", "bias": "Bullish", "momentum": 0.9, "strength": 0.8, "suppression": False, "suppression_reason": "", "structure_type": "trend", "structure_direction": "Bullish", "structure_valid": True, "context_zone": "supply", "context_level": 1928.0, "timestamp": "2025-08-31T02:00:00", "is_last_bias_candle": False, "engulfing_sequence": None, "engulfing_strength": None},
        "XAUUSD_i_H1": {"symbol": "XAUUSD_i", "timeframe": "H1", "bias": "Bullish", "momentum": 0.9, "strength": 0.8, "suppression": False, "suppression_reason": "", "structure_type": "trend", "structure_direction": "Bullish", "structure_valid": True, "context_zone": "supply", "context_level": 1930.0, "timestamp": "2025-08-31T01:00:00", "is_last_bias_candle": False, "engulfing_sequence": None, "engulfing_strength": None},
        "XAUUSD_i_H4": {"symbol": "XAUUSD_i", "timeframe": "H4", "bias": "Bullish", "momentum": 0.9, "strength": 0.8, "suppression": False, "suppression_reason": "", "structure_type": "trend", "structure_direction": "Bullish", "structure_valid": True, "context_zone": "supply", "context_level": 1935.0, "timestamp": "2025-08-31T00:00:00", "is_last_bias_candle": False, "engulfing_sequence": None, "engulfing_strength": None}
    }
}


response = requests.post(url, json=payload)
print("Status Code:", response.status_code)
print("Response JSON:", response.json())
