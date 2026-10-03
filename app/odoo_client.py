"""Odoo client — the system of record.

`mock` mode reads vendors/products from sample_data/odoo_seed.json and fabricates
purchase-order IDs in memory, so the pipeline runs with no Odoo instance.
`live` mode talks to a real Odoo over XML-RPC (the same calls the Odoo docs show
for `res.partner`, `product.product`, and `purchase.order`).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .config import settings

_SEED_PATH = Path(__file__).resolve().parent.parent / "sample_data" / "odoo_seed.json"


class OdooClient:
    def __init__(self) -> None:
        self.mode = settings.odoo_mode
        self._po_counter = 4000
        self._lock = threading.Lock()
        if self.mode == "mock":
            data = json.loads(_SEED_PATH.read_text())
            self._vendors = data["vendors"]
            self._products = data["products"]
        else:
            self._connect_live()

    # ── live connection ──────────────────────────────────────────────────────
    def _connect_live(self) -> None:
        import xmlrpc.client

        common = xmlrpc.client.ServerProxy(f"{settings.odoo_url}/xmlrpc/2/common")
        self._uid = common.authenticate(
            settings.odoo_db, settings.odoo_username, settings.odoo_password, {}
        )
        if not self._uid:
            raise RuntimeError("Odoo authentication failed — check ODOO_* settings.")
        self._models = xmlrpc.client.ServerProxy(f"{settings.odoo_url}/xmlrpc/2/object")

    def _execute(self, model: str, method: str, *args):
        return self._models.execute_kw(
            settings.odoo_db, self._uid, settings.odoo_password, model, method, *args
        )

    # ── catalog (read) ─────────────────────────────────────────────────────────
    def list_vendors(self) -> list[dict]:
        """Vendors (res.partner with supplier_rank > 0)."""
        if self.mode == "mock":
            return self._vendors
        return self._execute(
            "res.partner",
            "search_read",
            [[["supplier_rank", ">", 0]]],
            {"fields": ["id", "name", "email"], "limit": 200},
        )

    def list_products(self) -> list[dict]:
        """Purchasable products (product.product)."""
        if self.mode == "mock":
            return self._products
        return self._execute(
            "product.product",
            "search_read",
            [[["purchase_ok", "=", True]]],
            {"fields": ["id", "name", "default_code", "standard_price"], "limit": 500},
        )

    # ── purchase order (write) ───────────────────────────────────────────────
    def create_purchase_order(
        self, vendor_id: int, lines: list[dict], origin: str = ""
    ) -> int:
        """Create a draft PO. `lines` items: {product_id, product_qty, price_unit, name}."""
        if self.mode == "mock":
            with self._lock:
                self._po_counter += 1
                return self._po_counter

        order_lines = [
            (
                0,
                0,
                {
                    "product_id": ln["product_id"],
                    "name": ln.get("name", ""),
                    "product_qty": ln["product_qty"],
                    "price_unit": ln["price_unit"],
                },
            )
            for ln in lines
            if ln.get("product_id")
        ]
        return self._execute(
            "purchase.order",
            "create",
            [{"partner_id": vendor_id, "origin": origin, "order_line": order_lines}],
        )
