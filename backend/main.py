"""FastAPI application for Clinical Compass."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from backend.analytics import initialize_analytics, record_disease_lookup
from backend.request_limits import check_request_limit

from backend.boss import run_disease_lookup

@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_analytics()
    yield

app = FastAPI(title="Clinical Compass", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(',') if origin.strip()],
    allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


class DiseaseLookup(BaseModel):
    disease: str = Field(min_length=1, max_length=120)
    analytics_consent: bool = False


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/disease/{disease}")
async def disease_lookup(disease: str, request: Request) -> dict:
    disease = disease.strip()
    if not disease:
        raise HTTPException(status_code=400, detail="Disease is required")
    if len(disease) > 120:
        raise HTTPException(status_code=400, detail="Disease name must be 120 characters or fewer")
    client_key = request.client.host if request.client else "unknown"
    retry_after = check_request_limit(client_key)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many searches from this connection. Please wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        return await run_disease_lookup(disease)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Disease lookup failed") from exc


@app.post("/api/analytics/disease-lookup")
async def record_lookup(payload: DiseaseLookup) -> dict[str, bool | str]:
    if not payload.analytics_consent:
        return {"recorded": False}
    canonical = record_disease_lookup(payload.disease.strip())
    return {"recorded": True, "disease": canonical}
