"""Tests for the core TrackerEngine module."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import yaml

from spend_tracker.core import TrackerEngine
from spend_tracker.models import (
    Alert,
    AlertSeverity,
    AlertType,
    Budget,
    Campaign,
    Platform,
    Spend,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_config(tmp_path) -> str:
    """Create a temporary config file for testing."""
    cfg = {
        "meta": {
            "access_token": "test_token_123",
            "ad_account_id": "act_99999",
        },
        "telegram": {
            "bot_token": "test_bot_token",
            "chat_id": "test_chat_123",
        },
        "thresholds": {
            "daily_soft_cap": 100.0,
            "daily_hard_cap": 200.0,
            "daily_account_cap": 1000.0,
            "spike_pct": 50.0,
            "anomaly_zscore": 2.5,
        },
    }
    path = tmp_path / "test_config.yaml"
    with open(path, "w") as f:
        yaml.dump(cfg, f)
    return str(path)


@pytest.fixture
def sample_campaign() -> Campaign:
    return Campaign(
        id="camp_001",
        name="Test Campaign Alpha",
        platform=Platform.META,
        daily_budget=150.0,
        status="ACTIVE",
    )


@pytest.fixture
def sample_spend() -> Spend:
    return Spend(
        campaign_id="camp_001",
        campaign_name="Test Campaign Alpha",
        amount=75.50,
        timestamp=datetime.now(timezone.utc),
        platform=Platform.META,
        impressions=5000,
        clicks=120,
    )


@pytest.fixture
def engine(sample_config) -> TrackerEngine:
    return TrackerEngine(config_path=sample_config)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestTrackerEngineInit:
    """Tests for TrackerEngine initialization."""

    def test_init_with_valid_config(self, engine: TrackerEngine) -> None:
        """Engine initializes and loads config."""
        assert engine.config_path is not None
        assert engine.config["meta"]["access_token"] == "test_token_123"
        assert engine.config["meta"]["ad_account_id"] == "act_99999"

    def test_init_default_budget(self, engine: TrackerEngine) -> None:
        """Default budget is created from config thresholds."""
        budget = engine.get_budget("nonexistent_campaign")
        assert budget is not None
        assert budget.soft_cap == 100.0
        assert budget.hard_cap == 200.0
        assert budget.spike_threshold_pct == 50.0
        assert budget.anomaly_zscore == 2.5

    def test_init_without_config_file(self) -> None:
        """Engine handles missing config gracefully."""
        engine = TrackerEngine(config_path="/nonexistent/config.yaml")
        assert engine.config == {}

    def test_init_with_custom_providers(self) -> None:
        """Engine accepts pre-configured providers."""
        mock_provider = MagicMock()
        providers = {"meta": mock_provider}
        engine = TrackerEngine(
            config_path="/nonexistent/config.yaml",
            providers=providers,
        )
        assert engine.providers["meta"] == mock_provider

    def test_init_missing_meta_config(self, tmp_path) -> None:
        """Engine handles config without meta section."""
        cfg = {"thresholds": {"daily_soft_cap": 50.0}}
        path = tmp_path / "minimal.yaml"
        with open(path, "w") as f:
            yaml.dump(cfg, f)
        engine = TrackerEngine(config_path=str(path))
        assert engine.providers == {}


# ---------------------------------------------------------------------------
# Budget / Thresholds
# ---------------------------------------------------------------------------

class TestTrackerEngineThresholds:
    """Tests for budget threshold checking."""

    def test_soft_cap_breach(self, engine: TrackerEngine) -> None:
        """Soft cap breach generates a WARNING alert."""
        engine._campaigns["camp_001"] = Campaign(
            id="camp_001", name="Test Campaign"
        )
        # Set soft cap at 100 — spend of 110 should trigger
        engine._budgets["camp_001"] = Budget(
            campaign_id="camp_001", soft_cap=100.0, hard_cap=200.0
        )
        spend = Spend(campaign_id="camp_001", amount=110.0)
        alerts = engine.check_thresholds({"camp_001": spend})
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.BUDGET_BREACH
        assert alerts[0].severity == AlertSeverity.WARNING

    def test_hard_cap_breach(self, engine: TrackerEngine) -> None:
        """Hard cap breach generates a CRITICAL alert."""
        engine._campaigns["camp_001"] = Campaign(
            id="camp_001", name="Test Campaign"
        )
        engine._budgets["camp_001"] = Budget(
            campaign_id="camp_001", soft_cap=100.0, hard_cap=150.0
        )
        spend = Spend(campaign_id="camp_001", amount=160.0)
        alerts = engine.check_thresholds({"camp_001": spend})
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.BUDGET_BREACH
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_hard_cap_skips_soft_alert(self, engine: TrackerEngine) -> None:
        """Hard cap breach does NOT also generate a soft cap alert."""
        engine._budgets["camp_001"] = Budget(
            campaign_id="camp_001", soft_cap=100.0, hard_cap=150.0
        )
        spend = Spend(campaign_id="camp_001", amount=160.0)
        alerts = engine.check_thresholds({"camp_001": spend})
        assert len(alerts) == 1  # Only the hard cap alert

    def test_no_breach_below_caps(self, engine: TrackerEngine) -> None:
        """Spend below both caps generates no alerts."""
        engine._budgets["camp_001"] = Budget(
            campaign_id="camp_001", soft_cap=100.0, hard_cap=150.0
        )
        spend = Spend(campaign_id="camp_001", amount=30.0)
        alerts = engine.check_thresholds({"camp_001": spend})
        assert len(alerts) == 0

    def test_breach_without_campaign_name(self, engine: TrackerEngine) -> None:
        """Alert uses spend.campaign_name when campaign not cached."""
        engine._budgets["camp_001"] = Budget(
            campaign_id="camp_001", soft_cap=50.0
        )
        spend = Spend(
            campaign_id="camp_001",
            campaign_name="Direct Name",
            amount=60.0,
        )
        alerts = engine.check_thresholds({"camp_001": spend})
        assert len(alerts) == 1
        assert "Direct Name" in alerts[0].message

    def test_no_alerts_for_no_budget(self, engine: TrackerEngine) -> None:
        """Spend without any budget config does not crash."""
        # Clear budgets
        engine._budgets.clear()
        spend = Spend(campaign_id="orphan", amount=999.0)
        alerts = engine.check_thresholds({"orphan": spend})
        assert len(alerts) == 0

    def test_mixed_budgets(self, engine: TrackerEngine) -> None:
        """Multiple campaigns with different budgets are evaluated independently."""
        engine._budgets["a"] = Budget(campaign_id="a", soft_cap=50.0)
        engine._budgets["b"] = Budget(campaign_id="b", soft_cap=100.0)
        spends = {
            "a": Spend(campaign_id="a", amount=60.0),
            "b": Spend(campaign_id="b", amount=40.0),
        }
        alerts = engine.check_thresholds(spends)
        assert len(alerts) == 1
        assert alerts[0].campaign_id == "a"


# ---------------------------------------------------------------------------
# Account Cap
# ---------------------------------------------------------------------------

class TestTrackerEngineAccountCap:
    """Tests for account-level daily cap."""

    def test_account_cap_not_hit(self, engine: TrackerEngine) -> None:
        """Returns None when total spend is below cap."""
        result = engine.check_daily_account_cap(500.0)
        assert result is None

    def test_account_cap_hit(self, engine: TrackerEngine) -> None:
        """Returns CRITICAL alert when cap is hit."""
        result = engine.check_daily_account_cap(1000.0)
        assert result is not None
        assert result.alert_type == AlertType.DAILY_CAP_HIT
        assert result.severity == AlertSeverity.CRITICAL

    def test_account_cap_exceeded(self, engine: TrackerEngine) -> None:
        """Returns alert when cap is exceeded."""
        result = engine.check_daily_account_cap(1500.0)
        assert result is not None
        assert result.current_spend == 1500.0

    def test_account_cap_not_configured(self) -> None:
        """Returns None when no account cap is set."""
        engine = TrackerEngine(config_path="/nonexistent/config.yaml")
        result = engine.check_daily_account_cap(99999.0)
        assert result is None


# ---------------------------------------------------------------------------
# Campaign Lookup
# ---------------------------------------------------------------------------

class TestTrackerEngineCampaignLookup:
    """Tests for campaign retrieval."""

    def test_get_campaign_found(self, engine: TrackerEngine) -> None:
        """Returns campaign by ID when cached."""
        camp = Campaign(id="camp_001", name="Found")
        engine._campaigns["camp_001"] = camp
        assert engine.get_campaign("camp_001") == camp

    def test_get_campaign_not_found(self, engine: TrackerEngine) -> None:
        """Returns None for unknown campaign ID."""
        assert engine.get_campaign("ghost") is None

    def test_get_budget_fallback_to_default(self, engine: TrackerEngine) -> None:
        """Returns default budget for campaigns without explicit budget."""
        budget = engine.get_budget("unknown_campaign")
        assert budget is not None
        assert budget.campaign_id == "__default__"
        assert budget.soft_cap == 100.0

    def test_total_spend_today(self, engine: TrackerEngine) -> None:
        """total_spend_today sums cached spend."""
        engine._last_spend["a"] = 50.0
        engine._last_spend["b"] = 30.0
        assert engine.total_spend_today == 80.0

    def test_total_spend_empty(self, engine: TrackerEngine) -> None:
        """Returns 0 when no spend tracked."""
        assert engine.total_spend_today == 0.0


# ---------------------------------------------------------------------------
# Polling (mocked)
# ---------------------------------------------------------------------------

class TestTrackerEnginePolling:
    """Tests for polling with mocked providers."""

    @pytest.mark.asyncio
    async def test_poll_all_success(self, engine: TrackerEngine) -> None:
        """Successful poll returns spend data from mock provider."""
        mock = MagicMock()
        mock.fetch_campaigns.return_value = [
            Campaign(id="c1", name="Camp 1")
        ]
        mock.fetch_spend.return_value = [
            Spend(campaign_id="c1", amount=42.0)
        ]
        engine._providers["meta"] = mock

        results = await engine.poll_all_campaigns()
        assert "c1" in results
        assert results["c1"].amount == 42.0
        assert engine._last_spend["c1"] == 42.0

    @pytest.mark.asyncio
    async def test_poll_all_provider_error(self, engine: TrackerEngine) -> None:
        """Provider error is caught and logged, doesn't crash."""
        mock = MagicMock()
        mock.fetch_campaigns.side_effect = RuntimeError("API timeout")
        engine._providers["meta"] = mock

        results = await engine.poll_all_campaigns()
        assert results == {}

    @pytest.mark.asyncio
    async def test_poll_single_campaign(self, engine: TrackerEngine) -> None:
        """Polling a single campaign returns its spend."""
        mock = MagicMock()
        mock.fetch_campaigns.return_value = [
            Campaign(id="c1", name="Camp 1"),
            Campaign(id="c2", name="Camp 2"),
        ]
        mock.fetch_campaign_spend.return_value = Spend(
            campaign_id="c1", amount=99.0
        )
        engine._providers["meta"] = mock

        result = await engine.poll_campaign("c1")
        assert result is not None
        assert result.amount == 99.0

    @pytest.mark.asyncio
    async def test_poll_campaign_not_found(self, engine: TrackerEngine) -> None:
        """Returns None when campaign not found in any provider."""
        mock = MagicMock()
        mock.fetch_campaigns.return_value = []
        engine._providers["meta"] = mock

        result = await engine.poll_campaign("ghost_campaign")
        assert result is None
