from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

STARTED_AT = time.time()

app = FastAPI(title="Super-Agent Orchestration Demo", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "uptime_s": round(time.time() - STARTED_AT, 1),
        "provider": settings.provider.base_url,
        "model_main": settings.provider.model_main,
        "model_sub": settings.provider.model_sub,
        "fallback_configured": settings.fallback is not None,
    }