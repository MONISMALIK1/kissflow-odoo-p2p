"""Orchestration: Kissflow request → AI assessment → Odoo PO → status back to Kissflow.

This is the code-controlled workflow (not an open-ended agent) — we own the loop:
read catalog, ask the AI layer for a verdict, and act on it deterministically.
"""

from __future__ import annotations

import logging

from . import ai_layer
from .kissflow_client import KissflowClient
from .models import PipelineResult, PurchaseRequest
from .odoo_client import OdooClient

log = logging.getLogger("pipeline")


def process_request(
    request: PurchaseRequest,
    odoo: OdooClient | None = None,
    kissflow: KissflowClient | None = None,
) -> PipelineResult:
    odoo = odoo or OdooClient()
    kissflow = kissflow or KissflowClient()
    actions: list[str] = []

    # 1. Pull the Odoo catalog the AI layer matches against.
    vendors = odoo.list_vendors()
    products = odoo.list_products()
    actions.append(f"Loaded {len(vendors)} vendors / {len(products)} products from Odoo.")

    # 2. AI layer: extract, match, flag, recommend.
    assessment = ai_layer.assess(request, vendors, products)
    actions.append(f"AI recommendation: {assessment.recommendation}.")

    result = PipelineResult(request_id=request.request_id, assessment=assessment)

    # 3. Act on the recommendation.
    if assessment.recommendation == "auto_approve" and assessment.matched_vendor_id:
        po_lines = [
            {
                "product_id": d.matched_product_id,
                "name": d.description,
                "product_qty": d.quantity,
                "price_unit": d.unit_price,
            }
            for d in assessment.line_items
            if d.matched_product_id
        ]
        po_id = odoo.create_purchase_order(
            vendor_id=assessment.matched_vendor_id,
            lines=po_lines,
            origin=f"Kissflow {request.request_id}",
        )
        result.odoo_purchase_order_id = po_id
        actions.append(f"Created Odoo purchase order #{po_id}.")
        status, note = "Approved", f"Auto-approved. Odoo PO #{po_id} created."
    elif assessment.recommendation == "reject":
        status = "Rejected"
        note = assessment.recommendation_reason
    else:
        status = "Needs Review"
        note = assessment.recommendation_reason

    # 4. Sync the outcome back to Kissflow so the requester sees it.
    result.kissflow_synced = kissflow.sync_status(request.request_id, status, note)
    actions.append(f"Synced status '{status}' back to Kissflow.")

    result.actions = actions
    return result
