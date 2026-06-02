"""Abstract base class for ad platform providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from spend_tracker.models import Campaign, Spend


class BaseProvider(ABC):
    """Abstract interface for ad platform API integrations.

    Each platform (Meta, Google, TikTok, etc.) implements this interface
    to provide standardized spend data to the tracker engine.
    """

    def __init__(self, access_token: str, account_id: str, **kwargs: str) -> None:
        self.access_token = access_token
        self.account_id = account_id
        self._extra: dict[str, str] = kwargs

    @abstractmethod
    async def fetch_campaigns(self) -> List[Campaign]:
        """Fetch all active campaigns for the configured account.

        Returns:
            List of Campaign objects with basic metadata.
        """
        ...

    @abstractmethod
    async def fetch_spend(
        self,
        campaign_ids: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[Spend]:
        """Fetch spend data for one or more campaigns.

        Args:
            campaign_ids: If None, fetch for all campaigns.
            since: Start of time window (default: start of today UTC).
            until: End of time window (default: now).

        Returns:
            List of Spend data points.
        """
        ...

    @abstractmethod
    async def fetch_campaign_spend(
        self, campaign_id: str, since: Optional[datetime] = None, until: Optional[datetime] = None
    ) -> Spend:
        """Fetch current spend for a single campaign.

        Args:
            campaign_id: The campaign to query.
            since: Start of time window.
            until: End of time window.

        Returns:
            A single Spend object aggregated for the time window.
        """
        ...

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Human-readable platform name (e.g. 'Meta Ads')."""
        ...

    async def health_check(self) -> bool:
        """Check if the provider can reach its API.

        Returns:
            True if the API is reachable and credentials are valid.
        """
        try:
            await self.fetch_campaigns()
            return True
        except Exception:
            return False
