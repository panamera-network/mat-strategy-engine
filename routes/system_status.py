import psutil
import GPUtil
from fastapi import APIRouter
import MetaTrader5 as mt5  # Assuming MT5 is installed and configured

router = APIRouter()

@router.get("/system-status")
async def get_system_status():
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory().percent

    gpus = GPUtil.getGPUs()
    gpu = {
        "name": gpus[0].name,
        "load": gpus[0].load * 100,
        "memory": gpus[0].memoryUtil * 100
    } if gpus else None

    llm_status = {
        "model": "GPT-4",
        "loaded": True,
        "response_time": 120.5  # ms
    }

    services = {
        "backend": "running",
        "strategy": "active"
    }

    mt5_initialized = mt5.initialize()
    mt5_status = {
        "initialized": mt5_initialized,
        "account": mt5.account_info()._asdict() if mt5_initialized else None,
        "terminal": mt5.terminal_info()._asdict() if mt5_initialized else None,
        "symbols_count": len(mt5.symbols_get() or []),
        "symbols_available": mt5.symbols_get() is not None
    }

    return {
        "cpu": cpu,
        "ram": ram,
        "gpu": gpu,
        "llm": llm_status,
        "services": services,
        "mt5": mt5_status
    }
