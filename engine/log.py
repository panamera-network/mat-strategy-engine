from datetime import datetime, timezone

def log_suppression(symbol: str, tf: str, reason: str):
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[SUPPRESSION] {timestamp} | {symbol} [{tf}] → {reason}")

def log_error(symbol: str, tf: str, context: str, message: str):
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[ERROR] {timestamp} | {symbol} [{tf}] | {context} → {message}")

import json

def log_trace(symbol: str, tf: str, context: str, data: dict):
    timestamp = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(data, indent=2)
    print(f"[TRACE] {timestamp} | {symbol} [{tf}] | {context} →\n{payload}")

def log_success(symbol: str, tf: str, context: str, message: str):
    print(f"[{symbol} | {tf}] {context} ✅ {message}")

def log_warning(symbol: str, tf: str, context: str, message: str):
    print(f"[{symbol} | {tf}] {context} ⚠️ {message}")

def log_event(level: str, symbol: str, tf: str, context: str, message: str):
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{level.upper()}] {timestamp} | {symbol} [{tf}] | {context} → {message}")
