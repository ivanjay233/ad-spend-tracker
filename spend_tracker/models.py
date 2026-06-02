"""Pydantic models for ad spend tracking data structures."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class Platform(str, Enum):
    """Supported ad platforms."""

    META = "meta"
    GOOGLE = "google"
    TIKTOK = "tiktok"
    TWITTER = "twitter"


class BudgetPeriod(str, Enum):
    """Budget period types."""

    DAILY = "daily"
    LIFETIME = "lifetime"
    WEEKLY = "weekly"


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """Types of alerts that can be triggered."""

    BUDGET_BREACH = "budget_breach"
    SPEND_SPIKE = "spend_spike"
    ANOMALY_DETECTED = "anomaly_detected"
    DAILY_CAP_HIT = "daily_cap_hit"
    PROVIDER_ERROR = "provider_error"


class Campaign(BaseModel):
    """Represents an advertising campaign."""

    id: str = Field(description="Platform-specific campaign ID")
    name: str = Field(description="Campaign name")
    platform: Platform = Field(default=Platform.META)
    daily_budget: Optional[float] = Field(
        default=None, ge=0, description="Daily budget in USD"
    )
    lifetime_budget: Optional[float] = Field(
        default=None, ge=0, description="Lifetime budget in USD"
    )
    status: str = Field(default="ACTIVE")
    currency: str = Field(default="USD")
    account_id: str = Field(default="", description="Ad account ID")

    @field_validator("daily_budget", "lifetime_budget", mode="before")
    @classmethod
    def coerce_none(cls, v: object) -> object:
        """Coerce empty string or zero to None for optional budgets."""
        if v == "" or v is None:
            return None
        return v


class Spend(BaseModel):
    """Represents a spend data point for a campaign at a point in time."""

    campaign_id: str = Field(description="Campaign ID")
    campaign_name: str = Field(default="", description="Campaign name")
    amount: float = Field(ge=0, description="Spend amount in account currency")
    currency: str = Field(default="USD")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    platform: Platform = Field(default=Platform.META)
    impressions: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    cpm: Optional[float] = Field(default=None, ge=0)
    cpc: Optional[float] = Field(default=None, ge=0)

    @property
    def cpm_computed(self) -> float:
        """Calculate CPM from impressions if not provided."""
        if self.cpm is not None:
            return self.cpm
        if self.impressions > 0:
            return (self.amount / self.impressions) * 1000.0
        return 0.0

    @property
    def cpc_computed(self) -> float:
        """Calculate CPC from clicks if not provided."""
        if self.cpc is not None:
            return self.cpc
        if self.clicks > 0:
            return self.amount / self.clicks
        return 0.0


class Budget(BaseModel):
    """Defines budget thresholds and rules for a campaign or account."""

    campaign_id: str = Field(description="Campaign ID this budget applies to")
    soft_cap: Optional[float] = Field(
        default=None, ge=0, description="Soft daily cap in USD (warning-level)"
    )
    hard_cap: Optional[float] = Field(
        default=None, ge=0, description="Hard daily cap in USD (critical-level)"
    )
    period: BudgetPeriod = Field(default=BudgetPeriod.DAILY)
    spike_threshold_pct: float = Field(
        default=50.0, ge=0, description="Percentage change to trigger spike alert"
    )
    anomaly_zscore: float = Field(
        default=2.5, ge=0, description="Z-score threshold for anomaly detection"
    )

    @field_validator("hard_cap")
    @classmethod
    def hard_cap_gte_soft_cap(cls, v: Optional[float], info: ValidationInfo) -> Optional[float]:
        """Ensure hard cap is >= soft cap if both are set."""
        soft = info.data.get("soft_cap")
        if v is not None and soft is not None and v < soft:
            raise ValueError("hard_cap must be >= soft_cap")
        return v


class Alert(BaseModel):
    """Represents a triggered alert."""

    id: str = Field(default="", description="Unique alert ID")
    campaign_id: str = Field(description="Campaign that triggered the alert")
    campaign_name: str = Field(default="")
    alert_type: AlertType
    severity: AlertSeverity = Field(default=AlertSeverity.WARNING)
    message: str = Field(description="Human-readable alert message")
    current_spend: float = Field(default=0.0, ge=0)
    threshold_value: Optional[float] = Field(default=None)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    acknowledged: bool = Field(default=False)
    platform: Platform = Field(default=Platform.META)

    def acknowledge(self) -> None:
        """Mark this alert as acknowledged."""
        self.acknowledged = True
