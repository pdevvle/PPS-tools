"""Marketing Hub settings, read from the environment (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
    pass

DEFAULT_BRAND_CONTEXT = (
    "Priority Print Service (priorityprintservice.com) is a commercial print shop. "
    "It prints business cards, brochures, booklets, flyers, postcards, signage and "
    "promotional products for small businesses, offers fast turnaround, and sells "
    "online with instant quotes."
)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class MarketingSettings:
    db_path: Path = Path("marketing.db")
    # Public base URL of this app; OAuth redirect URIs are built from it, so it
    # must match what is registered with each platform.
    base_url: str = "http://localhost:5050"
    # "auto" shows sample data until the first platform is connected.
    demo: str = "auto"
    app_password: Optional[str] = None
    secret_key: Optional[str] = None
    claude_model: str = "claude-opus-5-5"
    brand_context: str = DEFAULT_BRAND_CONTEXT
    # How long fetched metrics are reused before the platforms are asked again.
    cache_minutes: int = 15
    # Rules and one-click actions never move a budget by more than this in one step.
    max_budget_change_pct: float = 50.0

    @classmethod
    def from_env(cls) -> "MarketingSettings":
        return cls(
            db_path=Path(_env("MARKETING_DB_PATH", "marketing.db")),
            base_url=_env("MARKETING_BASE_URL", "http://localhost:5050").rstrip("/"),
            demo=(_env("MARKETING_DEMO", "auto").lower() or "auto"),
            app_password=_env("MARKETING_APP_PASSWORD") or None,
            secret_key=_env("MARKETING_SECRET_KEY") or _env("FLASK_SECRET_KEY") or None,
            claude_model=_env("MARKETING_CLAUDE_MODEL", "claude-opus-5-5"),
            brand_context=_env("MARKETING_BRAND_CONTEXT") or DEFAULT_BRAND_CONTEXT,
            cache_minutes=int(_env("MARKETING_CACHE_MINUTES", "15") or 15),
            max_budget_change_pct=float(_env("MARKETING_MAX_BUDGET_CHANGE_PCT", "50") or 50),
        )

    def redirect_uri(self, platform: str) -> str:
        return f"{self.base_url}/oauth/{platform}/callback"
