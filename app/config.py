"""Runtime configuration, loaded from environment / .env.

Every external dependency (Claude, Odoo, Kissflow) has a "mode" so the whole
pipeline can run with zero credentials for a demo, then flip to live one piece
at a time.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AI layer
    ai_mode: str = "live"  # live | offline
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"

    # Odoo
    odoo_mode: str = "mock"  # mock | live
    odoo_url: str = ""
    odoo_db: str = ""
    odoo_username: str = ""
    odoo_password: str = ""

    # Kissflow
    kissflow_mode: str = "mock"  # mock | live
    kissflow_account_id: str = ""
    kissflow_base_url: str = ""
    kissflow_process_id: str = "Purchase_Request"
    kissflow_access_key_id: str = ""
    kissflow_access_key_secret: str = ""

    # Business rules
    auto_approve_limit: float = 5000.0
    price_variance_factor: float = 1.25


settings = Settings()
