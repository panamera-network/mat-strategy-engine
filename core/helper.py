from datetime import datetime, timezone
from typing import Optional, Union


def get_utc_now(fmt: Optional[str] = None) -> Union[datetime, str]:
    now = datetime.now(timezone.utc)
    return now.strftime(fmt) if fmt else now

def get_tile_color(status: str) -> str:
    return {
        "Strong": "#00FF00",
        "Weak": "#FFA500",
        "Suppressed": "#FF0000"
    }.get(status, "#CCCCCC")

def mode_to_tf(mode: str) -> str:
    return "M5" if mode == "scalping" else "H1"

def format_duration(seconds: int) -> str:
    return f"{seconds // 60} min"