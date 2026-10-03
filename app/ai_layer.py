"""The AI layer — the part that turns plumbing into a product.

Given a raw purchase request + the Odoo catalog, Claude produces a structured
`P2PAssessment`: normalized line items, fuzzy matches to existing Odoo products
and vendors, a suggested expense category, flagged anomalies, and an
auto_approve / needs_review / reject recommendation.

Two modes:
  * live    — Claude with structured outputs (the schema is `P2PAssessment`) and
              prompt caching on the catalog (stable across requests → ~0.1x cost).
  * offline — a deterministic token-overlap heuristic, no API key needed, so the
              end-to-end demo runs anywhere. It is intentionally dumber than the
              live path — that gap is the point of the project.
"""

from __future__ import annotations

import json
import re

from .config import settings
from .models import Anomaly, LineItemDecision, P2PAssessment, PurchaseRequest


def assess(request: PurchaseRequest, vendors: list[dict], products: list[dict]) -> P2PAssessment:
    if settings.ai_mode == "offline":
        return _assess_offline(request, vendors, products)
    return _assess_live(request, vendors, products)


# ── live (Claude) ────────────────────────────────────────────────────────────
_SYSTEM_INSTRUCTIONS = """You are a procurement analyst for a UAE company. You sit \
between a Kissflow purchase-request workflow and an Odoo ERP.

Given a raw purchase request and the Odoo catalog (vendors + purchasable \
products) below, produce a structured assessment:
- Extract and normalize the line items (description, quantity, unit price). The \
  request may arrive as structured lines or as a single free-text blob — handle both.
- Match each line to an existing Odoo product by id using a fuzzy match on the \
  product name. Use null when there is no confident match, and set match_confidence \
  (0.0-1.0) honestly.
- Match the requested vendor to an Odoo vendor id (null if unknown).
- Suggest a sensible expense category (e.g. "IT Equipment", "Office Supplies", \
  "Software Subscriptions", "Marketing").
- Flag anomalies. Valid types: duplicate, price_variance, over_budget, \
  missing_info, unknown_vendor, other. Set severity low | medium | high.
- Give a recommendation: auto_approve | needs_review | reject, with a short reason.

Business rules:
- Auto-approve ONLY if the total is at or under {limit} {currency}, the vendor and \
  every line item are confidently matched, and there are no high-severity anomalies.
- Flag a line as price_variance (medium severity) if its unit price exceeds the \
  matched product's standard_price by more than {factor}x.
- An unknown vendor or unmatched line item is missing_info / unknown_vendor, not a reason \
  to auto-approve. Be conservative — prefer needs_review when unsure, reject only when \
  the request is unworkable (no vendor and no parseable lines)."""


def _assess_live(
    request: PurchaseRequest, vendors: list[dict], products: list[dict]
) -> P2PAssessment:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    instructions = _SYSTEM_INSTRUCTIONS.format(
        limit=settings.auto_approve_limit,
        currency=request.currency,
        factor=settings.price_variance_factor,
    )
    catalog = json.dumps(
        {"vendors": vendors, "products": products}, sort_keys=True, indent=2
    )

    response = client.messages.parse(
        model=settings.anthropic_model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[
            {"type": "text", "text": instructions},
            # Catalog is stable across requests → cache it (prefix match).
            {
                "type": "text",
                "text": f"ODOO CATALOG:\n{catalog}",
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[
            {
                "role": "user",
                "content": "Assess this purchase request:\n"
                + request.model_dump_json(indent=2),
            }
        ],
        output_format=P2PAssessment,
    )
    return response.parsed_output


# ── offline (heuristic) ──────────────────────────────────────────────────────
def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _best_match(query: str, candidates: list[dict], key: str = "name") -> tuple[dict | None, float]:
    q = _tokens(query)
    if not q:
        return None, 0.0
    best, best_score = None, 0.0
    for cand in candidates:
        c = _tokens(str(cand.get(key, "")))
        if not c:
            continue
        score = len(q & c) / len(q | c)  # Jaccard overlap
        if score > best_score:
            best, best_score = cand, score
    return (best, best_score) if best_score >= 0.34 else (None, best_score)


def _assess_offline(
    request: PurchaseRequest, vendors: list[dict], products: list[dict]
) -> P2PAssessment:
    anomalies: list[Anomaly] = []
    decisions: list[LineItemDecision] = []
    total = 0.0

    vendor, v_conf = _best_match(request.vendor_name, vendors)
    if vendor is None:
        anomalies.append(
            Anomaly(type="unknown_vendor", severity="high",
                    detail=f"No catalog vendor matches '{request.vendor_name}'.")
        )

    if not request.lines:
        anomalies.append(
            Anomaly(type="missing_info", severity="high",
                    detail="No structured line items (offline mode cannot parse free text — "
                           "the live AI layer can).")
        )

    for line in request.lines:
        product, p_conf = _best_match(line.description, products)
        line_total = line.quantity * line.unit_price
        total += line_total
        notes = ""
        if product is None:
            anomalies.append(
                Anomaly(type="missing_info", severity="medium",
                        detail=f"Line '{line.description}' did not match any catalog product.")
            )
        else:
            std = float(product.get("standard_price", 0) or 0)
            if std and line.unit_price > std * settings.price_variance_factor:
                anomalies.append(
                    Anomaly(type="price_variance", severity="medium",
                            detail=f"'{line.description}' at {line.unit_price} exceeds catalog "
                                   f"price {std} by >{settings.price_variance_factor}x.")
                )
                notes = "Price above catalog standard."
        decisions.append(
            LineItemDecision(
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                matched_product_id=product.get("id") if product else None,
                matched_product_name=product.get("name") if product else None,
                match_confidence=round(p_conf, 2),
                notes=notes,
            )
        )

    if total > settings.auto_approve_limit:
        anomalies.append(
            Anomaly(type="over_budget", severity="medium",
                    detail=f"Total {total:.2f} {request.currency} exceeds auto-approve limit "
                           f"{settings.auto_approve_limit:.2f}.")
        )

    high = any(a.severity == "high" for a in anomalies)
    all_lines_matched = bool(decisions) and all(d.matched_product_id for d in decisions)
    if high or not request.lines:
        recommendation = "reject" if not request.lines else "needs_review"
    elif (
        vendor is not None
        and all_lines_matched
        and total <= settings.auto_approve_limit
        and not anomalies
    ):
        recommendation = "auto_approve"
    else:
        recommendation = "needs_review"

    return P2PAssessment(
        summary=f"{len(decisions)} line(s), {len(anomalies)} anomaly(ies). "
                f"Vendor match: {vendor['name'] if vendor else 'none'}.",
        matched_vendor_id=vendor.get("id") if vendor else None,
        matched_vendor_name=vendor.get("name") if vendor else None,
        vendor_match_confidence=round(v_conf, 2),
        suggested_expense_category=_guess_category(decisions),
        line_items=decisions,
        anomalies=anomalies,
        recommendation=recommendation,
        recommendation_reason=_reason(recommendation, anomalies),
        total_amount=round(total, 2),
        currency=request.currency,
    )


_CATEGORY_HINTS = {
    "IT Equipment": {"laptop", "monitor", "keyboard", "mouse", "dock", "macbook", "dell"},
    "Software Subscriptions": {"license", "subscription", "saas", "software", "seat", "seats"},
    "Office Supplies": {"chair", "desk", "paper", "stationery", "pen"},
    "Marketing": {"ads", "campaign", "advertising", "swag", "booth"},
}


def _guess_category(decisions: list[LineItemDecision]) -> str:
    toks: set[str] = set()
    for d in decisions:
        toks |= _tokens(d.description)
    best, best_hits = "General", 0
    for cat, hints in _CATEGORY_HINTS.items():
        hits = len(toks & hints)
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


def _reason(recommendation: str, anomalies: list[Anomaly]) -> str:
    if recommendation == "auto_approve":
        return "Within limit, vendor and all lines matched, no anomalies."
    if recommendation == "reject":
        return "Request is unworkable as submitted."
    flagged = ", ".join(sorted({a.type for a in anomalies})) or "low confidence on matches"
    return f"Routed for human review: {flagged}."
