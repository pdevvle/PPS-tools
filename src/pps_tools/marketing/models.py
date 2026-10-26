"""Normalized data shapes shared by every ad platform connector.

Each platform reports in its own units (Google in micros, Meta in cents,
X in local micros, ...). Connectors convert everything into these
dataclasses so the dashboard, rules engine and AI features only ever
see one shape: money as floats in the account currency, dates as ISO
strings, statuses as ACTIVE / PAUSED / REMOVED / OTHER.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

# Campaign statuses after normalization. Connectors keep the platform's own
# value in `raw_status` for display.
ACTIVE = "ACTIVE"
PAUSED = "PAUSED"
REMOVED = "REMOVED"
OTHER = "OTHER"
STATUSES = (ACTIVE, PAUSED, REMOVED, OTHER)


@dataclass(frozen=True)
class Network:
    """A place ads or posts appear. Meta's single connector feeds two of these."""

    key: str
    label: str
    slot: int  # categorical color slot (1-8); 0 = neutral gray


# Order is the categorical color order used in every chart; color follows the
# network everywhere in the UI, never its rank in a given chart.
NETWORKS: dict[str, Network] = {
    n.key: n
    for n in (
        Network("google", "Google Ads", 1),
        Network("facebook", "Facebook", 2),
        Network("instagram", "Instagram", 3),
        Network("pinterest", "Pinterest", 4),
        Network("x", "X (Twitter)", 5),
        Network("linkedin", "LinkedIn", 6),
        Network("tiktok", "TikTok", 7),
        Network("microsoft", "Microsoft Ads", 8),
        Network("other", "Other Meta placements", 0),
    )
}


def network_for(key: str) -> Network:
    return NETWORKS.get(key) or NETWORKS["other"]


@dataclass
class AdAccount:
    platform: str
    account_id: str
    name: str
    currency: str = "USD"
    timezone: Optional[str] = None
    enabled: bool = True
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AdAccount":
        return cls(**data)


@dataclass
class Campaign:
    platform: str
    account_id: str
    campaign_id: str
    name: str
    status: str
    raw_status: str = ""
    objective: Optional[str] = None
    daily_budget: Optional[float] = None
    lifetime_budget: Optional[float] = None
    currency: str = "USD"
    # False when the budget lives somewhere we can't safely edit
    # (Meta ad-set budgets, Google shared budgets, ...).
    budget_editable: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return campaign_key(self.platform, self.account_id, self.campaign_id)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["key"] = self.key
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Campaign":
        data = {k: v for k, v in data.items() if k != "key"}
        return cls(**data)


def campaign_key(platform: str, account_id: str, campaign_id: str) -> str:
    return f"{platform}:{account_id}:{campaign_id}"


def split_campaign_key(key: str) -> tuple[str, str, str]:
    platform, account_id, campaign_id = key.split(":", 2)
    return platform, account_id, campaign_id


@dataclass
class MetricRow:
    """One campaign, one network, one day."""

    platform: str
    network: str
    account_id: str
    campaign_id: str
    campaign_name: str
    date: str  # YYYY-MM-DD
    impressions: int = 0
    clicks: int = 0
    spend: float = 0.0
    conversions: float = 0.0
    conversion_value: float = 0.0
    currency: str = "USD"

    @property
    def campaign_key(self) -> str:
        return campaign_key(self.platform, self.account_id, self.campaign_id)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MetricRow":
        return cls(**data)


@dataclass
class Totals:
    impressions: int = 0
    clicks: int = 0
    spend: float = 0.0
    conversions: float = 0.0
    conversion_value: float = 0.0

    def add(self, row: "MetricRow | Totals") -> None:
        self.impressions += row.impressions
        self.clicks += row.clicks
        self.spend += row.spend
        self.conversions += row.conversions
        self.conversion_value += row.conversion_value

    # Derived metrics are None when the denominator is zero, so the UI can
    # show "—" instead of a misleading 0 or infinity.

    @property
    def ctr(self) -> Optional[float]:
        return self.clicks / self.impressions if self.impressions else None

    @property
    def cpc(self) -> Optional[float]:
        return self.spend / self.clicks if self.clicks else None

    @property
    def cpm(self) -> Optional[float]:
        return self.spend / self.impressions * 1000 if self.impressions else None

    @property
    def cvr(self) -> Optional[float]:
        return self.conversions / self.clicks if self.clicks else None

    @property
    def cpa(self) -> Optional[float]:
        return self.spend / self.conversions if self.conversions else None

    @property
    def roas(self) -> Optional[float]:
        return self.conversion_value / self.spend if self.spend else None

    def metric(self, name: str) -> Optional[float]:
        if name in ("impressions", "clicks", "spend", "conversions", "conversion_value"):
            return float(getattr(self, name))
        return getattr(self, name)

    def to_dict(self) -> dict:
        return {
            "impressions": self.impressions,
            "clicks": self.clicks,
            "spend": round(self.spend, 2),
            "conversions": round(self.conversions, 2),
            "conversion_value": round(self.conversion_value, 2),
            "ctr": self.ctr,
            "cpc": self.cpc,
            "cpm": self.cpm,
            "cvr": self.cvr,
            "cpa": self.cpa,
            "roas": self.roas,
        }


@dataclass
class PublishTarget:
    """Somewhere a post can go: a Facebook Page, an Instagram account, a board..."""

    platform: str  # connector key
    network: str  # facebook | instagram | pinterest | x | linkedin
    target_id: str
    name: str
    kind: str  # page | instagram_account | board | profile | organization
    enabled: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.network}:{self.target_id}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["key"] = self.key
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PublishTarget":
        data = {k: v for k, v in data.items() if k != "key"}
        return cls(**data)


@dataclass
class PostContent:
    text: str
    link: Optional[str] = None
    image_url: Optional[str] = None
    title: Optional[str] = None  # Pinterest pin title


@dataclass
class PublishResult:
    ok: bool
    network: str
    target_id: str
    remote_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
