"""Typed data shapes shared across the pipeline.

Two families:
  * Inbound — what Kissflow sends us (a raw, possibly-messy purchase request).
  * Assessment — the structured verdict the AI layer returns. This doubles as the
    JSON schema Claude is constrained to via structured outputs, so keep it free
    of unsupported constraints (no min/max, no min_length).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Inbound: the Kissflow purchase request ───────────────────────────────────
class RequestLine(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float = 0.0


class PurchaseRequest(BaseModel):
    request_id: str
    requester: str
    department: str = ""
    vendor_name: str = ""
    currency: str = "AED"
    justification: str = ""
    lines: list[RequestLine] = Field(default_factory=list)
    # Free-text fallback: some Kissflow forms send one blob instead of line items.
    raw_text: str = ""


# ── Assessment: the AI layer's structured verdict ────────────────────────────
class LineItemDecision(BaseModel):
    description: str
    quantity: float
    unit_price: float
    matched_product_id: int | None = None
    matched_product_name: str | None = None
    match_confidence: float = 0.0  # 0.0–1.0
    notes: str = ""


class Anomaly(BaseModel):
    # type: duplicate | price_variance | over_budget | missing_info |
    #       unknown_vendor | other
    type: str
    severity: str  # low | medium | high
    detail: str


class P2PAssessment(BaseModel):
    summary: str
    matched_vendor_id: int | None = None
    matched_vendor_name: str | None = None
    vendor_match_confidence: float = 0.0
    suggested_expense_category: str = ""
    line_items: list[LineItemDecision] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)
    # recommendation: auto_approve | needs_review | reject
    recommendation: str = "needs_review"
    recommendation_reason: str = ""
    total_amount: float = 0.0
    currency: str = "AED"


# ── Result: what the pipeline returns to the caller ──────────────────────────
class PipelineResult(BaseModel):
    request_id: str
    assessment: P2PAssessment
    odoo_purchase_order_id: int | None = None
    kissflow_synced: bool = False
    actions: list[str] = Field(default_factory=list)
