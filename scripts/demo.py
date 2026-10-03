"""End-to-end demo — no Kissflow or Odoo account required.

    python scripts/demo.py            # uses AI_MODE from .env (offline works with no key)
    AI_MODE=offline python scripts/demo.py
    AI_MODE=live    python scripts/demo.py   # needs ANTHROPIC_API_KEY

Runs every sample request from sample_data/requests.json through the full pipeline
and prints the assessment + what would happen in Odoo/Kissflow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import pipeline  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import PurchaseRequest  # noqa: E402

RULE = "─" * 72


def main() -> None:
    requests = json.loads((ROOT / "sample_data" / "requests.json").read_text())
    print(RULE)
    print(f" AI_MODE={settings.ai_mode}  ODOO_MODE={settings.odoo_mode}  "
          f"KISSFLOW_MODE={settings.kissflow_mode}  model={settings.anthropic_model}")
    print(RULE)

    for raw in requests:
        req = PurchaseRequest(**raw)
        result = pipeline.process_request(req)
        a = result.assessment

        print(f"\n▶ {req.request_id} — {req.requester} ({req.department or 'n/a'})")
        print(f"  requested vendor : {req.vendor_name or '(free text)'}")
        print(f"  AI summary       : {a.summary}")
        print(f"  vendor match     : {a.matched_vendor_name or '—'} "
              f"(conf {a.vendor_match_confidence})")
        print(f"  category         : {a.suggested_expense_category}")
        print(f"  total            : {a.total_amount} {a.currency}")
        for d in a.line_items:
            tag = f"→ #{d.matched_product_id} {d.matched_product_name}" if d.matched_product_id else "→ UNMATCHED"
            print(f"    • {d.quantity} × {d.description} @ {d.unit_price}  {tag} "
                  f"(conf {d.match_confidence})")
        for an in a.anomalies:
            print(f"    ⚠ [{an.severity}] {an.type}: {an.detail}")
        print(f"  RECOMMENDATION   : {a.recommendation.upper()} — {a.recommendation_reason}")
        if result.odoo_purchase_order_id:
            print(f"  Odoo PO created  : #{result.odoo_purchase_order_id}")
        print(f"  Kissflow synced  : {result.kissflow_synced}")

    print("\n" + RULE)


if __name__ == "__main__":
    main()
