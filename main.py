import sys

# Windows console defaults to cp1252, which can't encode the unicode
# arrows/emoji used in print()/logging calls throughout core/ and mt5/.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi.middleware.cors import CORSMiddleware

from routes.system_status import router as status_router

from routes.mt5_status import router as mt5_router

from api.core_router import router as core_router


# 🔁 Define lifespan first
@asynccontextmanager
async def lifespan(app: FastAPI):
    FastAPICache.init(InMemoryBackend(), prefix="my_prefix")
    print("FastAPI Cache initialized")

    yield  # ⏳ App runs here

    print("App shutting down")

# 🚀 Create the app
app = FastAPI(lifespan=lifespan)

# 🌐 CORS setup
origins = [
    "http://localhost:5173",
    "http://localhost:5174",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 📦 Route mounting
app.include_router(status_router, prefix="/api")

app.include_router(mt5_router, prefix="/api")

app.include_router(core_router, prefix="/core")