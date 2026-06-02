"""Report generation — daily and weekly spend summaries."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from spend_tracker.models import Alert, Campaign, Spend

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates formatted daily and weekly spend summary reports.

    Aggregates spend data across campaigns and provides human-readable
    reports suitable for printing to console or sending via Telegram.
    """

    def __init__(self) -> None:
        self._spend_history: Dict[str, List[Spend]] = {}
        self._alerts_history: List[Alert] = []

    def record_spend(self, spend: Spend) -> None:
        """Record a spend data point for report aggregation."""
        if spend.campaign_id not in self._spend_history:
            self._spend_history[spend.campaign_id] = []
        self._spend_history[spend.campaign_id].append(spend)

    def record_spends(self, spends: List[Spend]) -> None:
        """Record multiple spend data points."""
        for spend in spends:
            self.record_spend(spend)

    def record_alert(self, alert: Alert) -> None:
        """Record an alert for inclusion in reports."""
        self._alerts_history.append(alert)

    def record_alerts(self, alerts: List[Alert]) -> None:
        """Record multiple alerts."""
        self._alerts_history.extend(alerts)

    def generate_daily_report(
        self,
        campaign_spends: Dict[str, Spend],
        campaigns: Optional[Dict[str, Campaign]] = None,
        alerts: Optional[List[Alert]] = None,
    ) -> str:
        """Generate a formatted daily spend summary report.

        Args:
            campaign_spends: Current spend data keyed by campaign_id.
            campaigns: Campaign metadata for names and budgets.
            alerts: Recent alerts to include in the report.

        Returns:
            Formatted report string.
        """
        today = date.today()
        lines: list[str] = [
            "📊 *Ad Spend Daily Report*",
            f"📅 {today.strftime('%A, %B %d, %Y')}",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        total_spend = 0.0
        table_lines: list[str] = []
        for campaign_id, spend in campaign_spends.items():
            name = spend.campaign_name or campaign_id
            budget_info = ""
            if campaigns and campaign_id in campaigns:
                camp = campaigns[campaign_id]
                if camp.daily_budget:
                    pct = (spend.amount / camp.daily_budget) * 100
                    budget_info = f" ({pct:.1f}% of ${camp.daily_budget:.0f} budget)"

            table_lines.append(
                f"• *{name}*: ${spend.amount:.2f}{budget_info}"
            )
            total_spend += spend.amount

        lines.extend(table_lines)
        lines.append("")
        lines.append(f"*Total Spend:* ${total_spend:.2f}")
        lines.append("")

        # Add alerts section
        all_alerts = alerts or self._alerts_history
        if all_alerts:
            recent = [a for a in all_alerts if a.timestamp.date() == today]
            if recent:
                lines.append("━━━━━━━━━━━━━━━━━━━━")
                lines.append("*Today's Alerts:*")
                for a in recent[-5:]:  # last 5
                    emoji = "🚨" if a.severity.value == "critical" else "⚠️"
                    lines.append(f"  {emoji} {a.message[:120]}")
                lines.append("")

        lines.append(f"🕐 Generated at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        return "\n".join(lines)

    def generate_weekly_report(
        self,
        campaign_spends: Dict[str, Spend],
        campaigns: Optional[Dict[str, Campaign]] = None,
        alerts: Optional[List[Alert]] = None,
    ) -> str:
        """Generate a formatted weekly spend summary report.

        Args:
            campaign_spends: Current spend data keyed by campaign_id.
            campaigns: Campaign metadata for names and budgets.
            alerts: Recent alerts to include.

        Returns:
            Formatted report string with weekly aggregates.
        """
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        lines: list[str] = [
            "📈 *Ad Spend Weekly Report*",
            f"📅 {week_start.strftime('%b %d')} — {today.strftime('%b %d, %Y')}",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        total_spend = 0.0
        total_impressions = 0
        total_clicks = 0

        # Aggregate weekly data from history
        weekly_data: Dict[str, Dict[str, float | int]] = {}
        for campaign_id, spends in self._spend_history.items():
            weekly_amount = 0.0
            weekly_impressions = 0
            weekly_clicks = 0
            for s in spends:
                s_date = s.timestamp.date() if s.timestamp else today
                if week_start <= s_date <= today:
                    weekly_amount += s.amount
                    weekly_impressions += s.impressions
                    weekly_clicks += s.clicks

            if weekly_amount > 0 or campaign_id in campaign_spends:
                current = campaign_spends.get(campaign_id)
                curr_amount = current.amount if current else 0.0
                total_weekly = weekly_amount + (
                    curr_amount if today == date.today() else 0
                )

                weekly_data[campaign_id] = {
                    "spend": total_weekly,
                    "impressions": weekly_impressions,
                    "clicks": weekly_clicks,
                }
                total_spend += total_weekly
                total_impressions += weekly_impressions
                total_clicks += weekly_clicks

        if not weekly_data:
            lines.append("No data available for this week.")
        else:
            for campaign_id, data in weekly_data.items():
                name = campaign_id
                if campaigns and campaign_id in campaigns:
                    name = campaigns[campaign_id].name

                spend_val = data["spend"]
                imp = data["impressions"]
                clk = data["clicks"]
                cpm = (spend_val / imp) * 1000 if imp and isinstance(spend_val, (int, float)) else 0

                lines.append(
                    f"• *{name}*: ${spend_val:.2f} "
                    f"| {imp:,} imps | {clk:,} clicks | "
                    f"CPM ${cpm:.2f}"
                )

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"*Weekly Total:* ${total_spend:.2f}")
        lines.append(f"*Total Impressions:* {total_impressions:,}")
        lines.append(f"*Total Clicks:* {total_clicks:,}")
        if total_impressions > 0:
            overall_cpm = (total_spend / total_impressions) * 1000
            lines.append(f"*Overall CPM:* ${overall_cpm:.2f}")

        # Alert summary
        all_alerts = alerts or self._alerts_history
        if all_alerts:
            week_alerts = [a for a in all_alerts if a.timestamp.date() >= week_start]
            if week_alerts:
                critical_count = sum(1 for a in week_alerts if a.severity.value == "critical")
                warning_count = sum(1 for a in week_alerts if a.severity.value == "warning")
                lines.append("")
                lines.append(f"*Alerts this week:* {len(week_alerts)} "
                             f"(🚨 {critical_count} critical, ⚠️ {warning_count} warnings)")

        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all recorded history."""
        self._spend_history.clear()
        self._alerts_history.clear()
