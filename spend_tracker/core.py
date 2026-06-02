"""Core tracker engine — polls ad platforms, checks thresholds, triggers alerts."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import yaml

from spend_tracker.models import (
    Alert,
    AlertSeverity,
    AlertType,
    Budget,
    Campaign,
    Platform,
    Spend,
)
from spend_tracker.providers.base import BaseProvider
from spend_tracker.providers.meta import MetaProvider

logger = logging.getLogger(__name__)


class TrackerEngine:
    """Main engine that polls ad platforms, enforces budgets, and generates alerts.

    Usage:
        engine = TrackerEngine(config_path="config.yaml")
        results = await engine.poll_all_campaigns()
        alerts = engine.check_thresholds(results)
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        providers: Optional[Dict[str, BaseProvider]] = None,
    ) -> None:
        self.config_path = config_path
        self.config: dict = {}
        self._providers: dict[str, BaseProvider] = providers or {}
        self._budgets: dict[str, Budget] = {}
        self._campaigns: dict[str, Campaign] = {}
        self._last_spend: dict[str, float] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        try:
            with open(self.config_path) as f:
                self.config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning("Config file %s not found, using defaults", self.config_path)
            self.config = {}

        # Initialize providers from config
        meta_cfg = self.config.get("meta", {})
        if meta_cfg.get("access_token") and meta_cfg.get("ad_account_id"):
            self._providers[Platform.META.value] = MetaProvider(
                access_token=meta_cfg["access_token"],
                account_id=meta_cfg["ad_account_id"],
            )

        # Parse budget thresholds
        thresholds = self.config.get("thresholds", {})
        default_budget = Budget(
            campaign_id="__default__",
            soft_cap=thresholds.get("daily_soft_cap", 100.0),
            hard_cap=thresholds.get("daily_hard_cap", 150.0),
            spike_threshold_pct=thresholds.get("spike_pct", 50.0),
            anomaly_zscore=thresholds.get("anomaly_zscore", 2.5),
        )
        self._budgets["__default__"] = default_budget

        # Parse per-campaign budgets
        for camp_cfg in thresholds.get("campaigns", []):
            camp_id = camp_cfg.get("id", "")
            if camp_id:
                self._budgets[camp_id] = Budget(
                    campaign_id=camp_id,
                    soft_cap=camp_cfg.get("soft_cap"),
                    hard_cap=camp_cfg.get("hard_cap"),
                    spike_threshold_pct=camp_cfg.get("spike_pct", default_budget.spike_threshold_pct),
                    anomaly_zscore=camp_cfg.get("anomaly_zscore", default_budget.anomaly_zscore),
                )

    @property
    def providers(self) -> Dict[str, BaseProvider]:
        """Get registered providers, auto-initializing from config if needed."""
        return self._providers

    async def poll_all_campaigns(self) -> Dict[str, Spend]:
        """Poll all providers for current campaign spend data.

        Returns:
            Dict mapping campaign_id -> Spend object.
        """
        results: dict[str, Spend] = {}
        for platform_name, provider in self._providers.items():
            try:
                campaigns = await provider.fetch_campaigns()
                for campaign in campaigns:
                    self._campaigns[campaign.id] = campaign

                spends = await provider.fetch_spend()
                for spend in spends:
                    results[spend.campaign_id] = spend
                    self._last_spend[spend.campaign_id] = spend.amount

            except Exception as exc:
                logger.error("Failed to poll %s provider: %s", platform_name, exc)

        logger.info("Polled %d campaigns from %d providers", len(results), len(self._providers))
        return results

    async def poll_campaign(self, campaign_id: str) -> Optional[Spend]:
        """Poll spend for a single campaign.

        Args:
            campaign_id: The campaign to poll.

        Returns:
            Spend object or None if the campaign is not found.
        """
        for provider in self._providers.values():
            try:
                # Check if this provider has this campaign
                campaigns = await provider.fetch_campaigns()
                if any(c.id == campaign_id for c in campaigns):
                    spend = await provider.fetch_campaign_spend(campaign_id)
                    self._last_spend[campaign_id] = spend.amount
                    return spend
            except Exception as exc:
                logger.debug("Campaign %s not found on provider: %s", campaign_id, exc)
        return None

    def check_thresholds(self, spends: Dict[str, Spend]) -> List[Alert]:
        """Evaluate spend data against configured budget thresholds.

        Args:
            spends: Dict of campaign_id -> Spend from poll_all_campaigns.

        Returns:
            List of triggered alerts.
        """
        alerts: list[Alert] = []

        for campaign_id, spend in spends.items():
            budget = self._budgets.get(campaign_id, self._budgets.get("__default__"))
            if budget is None:
                continue

            campaign = self._campaigns.get(campaign_id)
            campaign_name = campaign.name if campaign else spend.campaign_name

            # 1. Hard cap breach
            if budget.hard_cap is not None and spend.amount >= budget.hard_cap:
                alerts.append(
                    Alert(
                        campaign_id=campaign_id,
                        campaign_name=campaign_name,
                        alert_type=AlertType.BUDGET_BREACH,
                        severity=AlertSeverity.CRITICAL,
                        message=(
                            f"🚨 HARD CAP BREACH: {campaign_name} "
                            f"spent ${spend.amount:.2f} (cap: ${budget.hard_cap:.2f})"
                        ),
                        current_spend=spend.amount,
                        threshold_value=budget.hard_cap,
                    )
                )
                continue  # skip soft cap if hard is breached

            # 2. Soft cap breach
            if budget.soft_cap is not None and spend.amount >= budget.soft_cap:
                alerts.append(
                    Alert(
                        campaign_id=campaign_id,
                        campaign_name=campaign_name,
                        alert_type=AlertType.BUDGET_BREACH,
                        severity=AlertSeverity.WARNING,
                        message=(
                            f"⚠️ SOFT CAP REACHED: {campaign_name} "
                            f"spent ${spend.amount:.2f} (cap: ${budget.soft_cap:.2f})"
                        ),
                        current_spend=spend.amount,
                        threshold_value=budget.soft_cap,
                    )
                )

        return alerts

    def check_daily_account_cap(self, total_spend: float) -> Optional[Alert]:
        """Check if the total account-level daily spend cap has been hit.

        Args:
            total_spend: Sum of spend across all campaigns.

        Returns:
            An alert if the daily cap is hit, else None.
        """
        daily_cap = self.config.get("thresholds", {}).get("daily_account_cap")
        if daily_cap is not None and total_spend >= daily_cap:
            return Alert(
                campaign_id="__account__",
                campaign_name="Account Total",
                alert_type=AlertType.DAILY_CAP_HIT,
                severity=AlertSeverity.CRITICAL,
                message=(
                    f"🏁 DAILY ACCOUNT CAP HIT: ${total_spend:.2f} "
                    f"(cap: ${daily_cap:.2f})"
                ),
                current_spend=total_spend,
                threshold_value=daily_cap,
            )
        return None

    def get_campaign(self, campaign_id: str) -> Optional[Campaign]:
        """Look up a cached campaign by ID."""
        return self._campaigns.get(campaign_id)

    def get_budget(self, campaign_id: str) -> Optional[Budget]:
        """Get the budget config for a campaign (falls back to default)."""
        return self._budgets.get(campaign_id, self._budgets.get("__default__"))

    @property
    def total_spend_today(self) -> float:
        """Sum of last known spend across all tracked campaigns."""
        return sum(self._last_spend.values())
