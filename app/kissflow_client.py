"""Kissflow client — the human workflow layer.

After the ERP side is done, we push the outcome back so the requester sees status
inside Kissflow without ever logging into Odoo. `mock` mode just logs; `live` mode
posts a comment + status update to the process item via Kissflow's REST API.
"""

from __future__ import annotations

import logging

from .config import settings

log = logging.getLogger("kissflow")


class KissflowClient:
    def __init__(self) -> None:
        self.mode = settings.kissflow_mode

    def sync_status(self, request_id: str, status: str, note: str) -> bool:
        """Reflect the pipeline outcome back onto the Kissflow request item."""
        if self.mode == "mock":
            log.info("[kissflow mock] %s → %s :: %s", request_id, status, note)
            return True

        import urllib.request

        url = (
            f"{settings.kissflow_base_url}/process/2/{settings.kissflow_account_id}"
            f"/{settings.kissflow_process_id}/{request_id}/note"
        )
        payload = f'{{"Body": "[P2P bot] {status}: {note}"}}'.encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Access-Key-Id", settings.kissflow_access_key_id)
        req.add_header("X-Access-Key-Secret", settings.kissflow_access_key_secret)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the pipeline
            log.error("Kissflow sync failed for %s: %s", request_id, exc)
            return False
