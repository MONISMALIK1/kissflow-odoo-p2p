"""FastAPI middleware — the webhook Kissflow calls when a request is approved.

Run: uvicorn app.main:app --reload
Then POST a Kissflow purchase request to /webhooks/kissflow/purchase-request.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from . import pipeline
from .config import settings
from .models import PipelineResult, PurchaseRequest

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Kissflow → Odoo P2P bridge", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "ai_mode": settings.ai_mode,
        "odoo_mode": settings.odoo_mode,
        "kissflow_mode": settings.kissflow_mode,
        "model": settings.anthropic_model,
    }


@app.post("/webhooks/kissflow/purchase-request", response_model=PipelineResult)
def kissflow_purchase_request(request: PurchaseRequest) -> PipelineResult:
    """Kissflow posts an approved purchase request here; we run the P2P pipeline."""
    return pipeline.process_request(request)
