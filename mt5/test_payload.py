import time

def generate_mock_payload():
    current_ts = int(time.time())
    candle = {
        "timestamp": current_ts,
        "open": 1.1000,
        "high": 1.1020,
        "low": 1.0980,
        "close": 1.1010,
        "volume": 1000
    }

    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]
    payload = {
        "data": {
            "EURUSD_i": {
                tf: {
                    "candles": [candle]
                } for tf in timeframes
            }
        }
    }

    return payload
