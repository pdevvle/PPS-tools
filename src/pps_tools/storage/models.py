"""Data models for PPS-Tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Competitor:
    name: str
    display_name: str
    base_url: str
    is_active: bool = True
    is_dynamic: bool = False
    id: int | None = None


@dataclass
class Product:
    name: str
    display_name: str
    category: str
    id: int | None = None


@dataclass
class PricingUrl:
    competitor_id: int
    product_id: int
    url: str
    discovery_method: str = "config"
    is_dynamic: bool = False
    is_active: bool = True
    last_checked: str | None = None
    id: int | None = None


@dataclass
class PricePoint:
    competitor: str
    product: str
    quantity: int
    total_price: float
    unit_price: float | None = None
    paper_type: str | None = None
    size: str | None = None
    color_mode: str | None = None
    sides: str | None = None
    turnaround_days: int | None = None
    finish: str | None = None
    currency: str = "USD"
    scraped_at: str | None = None
    raw_text: str | None = None
    id: int | None = None
    competitor_id: int | None = None
    product_id: int | None = None

    def __post_init__(self):
        if self.unit_price is None and self.quantity > 0:
            self.unit_price = round(self.total_price / self.quantity, 4)


@dataclass
class OwnPricing:
    product: str
    quantity: int
    total_price: float
    paper_type: str | None = None
    size: str | None = None
    color_mode: str | None = None
    sides: str | None = None
    turnaround_days: int | None = None
    finish: str | None = None
    effective_date: str | None = None
    id: int | None = None
    product_id: int | None = None


@dataclass
class ScrapeRun:
    competitor_id: int
    product_id: int | None = None
    url: str | None = None
    status: str = "success"
    records_found: int = 0
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    id: int | None = None


@dataclass
class ComparisonRow:
    """A single row in a price comparison output."""
    product: str
    quantity: int
    own_price: float | None = None
    competitor_prices: dict[str, float] = field(default_factory=dict)
    own_unit_price: float | None = None
    competitor_unit_prices: dict[str, float] = field(default_factory=dict)

    @property
    def cheapest_competitor(self) -> str | None:
        if not self.competitor_prices:
            return None
        return min(self.competitor_prices, key=self.competitor_prices.get)

    @property
    def most_expensive_competitor(self) -> str | None:
        if not self.competitor_prices:
            return None
        return max(self.competitor_prices, key=self.competitor_prices.get)

    def price_diff_pct(self, competitor: str) -> float | None:
        """Percentage difference from own price. Positive = competitor is more expensive."""
        if self.own_price is None or competitor not in self.competitor_prices:
            return None
        if self.own_price == 0:
            return None
        return round(
            (self.competitor_prices[competitor] - self.own_price) / self.own_price * 100,
            1,
        )


@dataclass
class TrendPoint:
    """A data point in a price trend."""
    date: str
    price: float
    quantity: int
    competitor: str
    product: str
