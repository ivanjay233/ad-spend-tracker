"""Meta Ads API provider implementation.

Integrates with the Facebook Graph Marketing API to fetch campaign
spend data in real-time. Uses httpx for async HTTP requests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from spend_tracker.models import Campaign, Platform, Spend
from spend_tracker.providers.base import BaseProvider

logger = logging.getLogger(__name__)

META_API_BASE = "https://graph.facebook.com/v18.0"
DEFAULT_TIMEOUT = 30.0


class MetaProvider(BaseProvider):
    """Provider implementation for Meta (Facebook) Ads API."""

    def __init__(
        self,
        access_token: str,
        account_id: str,
        api_version: str = "v18.0",
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs: str,
    ) -> None:
        super().__init__(access_token, account_id, **kwargs)
        self.api_base = f"https://graph.facebook.com/{api_version}"
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def platform_name(self) -> str:
        return "Meta Ads"

    @property
    def _client_instance(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make an authenticated GET request to the Meta Graph API."""
        if params is None:
            params = {}
        params["access_token"] = self.access_token

        url = f"{self.api_base}/{path}"
        logger.debug("GET %s", url)

        response = await self._client_instance.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def fetch_campaigns(self) -> List[Campaign]:
        """Fetch all active campaigns from the Meta Ads account."""
        fields = "id,name,daily_budget,lifetime_budget,status,currency,account_id"
        path = f"act_{self.account_id}/campaigns"
        data = await self._get(path, params={"fields": fields, "limit": 100})

        campaigns: List[Campaign] = []
        for raw in data.get("data", []):
            campaign = Campaign(
                id=raw["id"],
                name=raw.get("name", "Unnamed"),
                platform=Platform.META,
                daily_budget=raw.get("daily_budget"),
                lifetime_budget=raw.get("lifetime_budget"),
                status=raw.get("status", "UNKNOWN"),
                currency=raw.get("currency", "USD"),
                account_id=raw.get("account_id", self.account_id),
            )
            campaigns.append(campaign)

        logger.info("Fetched %d campaigns from Meta Ads", len(campaigns))
        return campaigns

    async def fetch_spend(
        self,
        campaign_ids: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[Spend]:
        """Fetch spend data for campaigns within a time window."""
        if since is None:
            since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        if until is None:
            until = datetime.now(timezone.utc)

        since_str = since.isoformat()
        until_str = until.isoformat()

        spend_list: List[Spend] = []
        campaigns = await self.fetch_campaigns()

        for campaign in campaigns:
            if campaign_ids and campaign.id not in campaign_ids:
                continue

            spend = await self.fetch_campaign_spend(campaign.id, since, until)
            spend_list.append(spend)

        return spend_list

    async def fetch_campaign_spend(
        self, campaign_id: str, since: Optional[datetime] = None, until: Optional[datetime] = None
    ) -> Spend:
        """Fetch current spend for a single campaign via the Meta Insights API."""
        if since is None:
            since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        if until is None:
            until = datetime.now(timezone.utc)

        since_str = since.strftime("%Y-%m-%d")
        until_str = until.strftime("%Y-%m-%d")

        fields = "campaign_id,campaign_name,spend,impressions,clicks,cpm,cpc,date_start"
        path = f"{campaign_id}/insights"
        data = await self._get(
            path,
            params={
                "fields": fields,
                "time_range": f'{{"since":"{since_str}","until":"{until_str}"}}',
                "level": "campaign",
                "limit": 1,
            },
        )

        rows = data.get("data", [])
        if rows:
            row = rows[0]
            return Spend(
                campaign_id=row.get("campaign_id", campaign_id),
                campaign_name=row.get("campaign_name", ""),
                amount=float(row.get("spend", 0)),
                currency="USD",
                timestamp=datetime.now(timezone.utc),
                platform=Platform.META,
                impressions=int(row.get("impressions", 0)),
                clicks=int(row.get("clicks", 0)),
                cpm=float(row["cpm"]) if row.get("cpm") else None,
                cpc=float(row["cpc"]) if row.get("cpc") else None,
            )

        # Return zero-spend if no data yet today
        return Spend(
            campaign_id=campaign_id,
            campaign_name="",
            amount=0.0,
            timestamp=datetime.now(timezone.utc),
            platform=Platform.META,
        )

    async def health_check(self) -> bool:
        """Verify API connectivity by fetching the ad account."""
        try:
            await self._get(f"act_{self.account_id}", params={"fields": "name"})
            return True
        except Exception as exc:
            logger.warning("Meta Ads health check failed: %s", exc)
            return False
