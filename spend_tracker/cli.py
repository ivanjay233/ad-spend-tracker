"""Command-line interface for Ad Spend Tracker.

Usage:
    ad-spend track          Poll all campaigns and show spend
    ad-spend alert          Check thresholds and send alerts
    ad-spend report         Generate daily or weekly report
    ad-spend status         Show current system status
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

import click

from spend_tracker import __version__
from spend_tracker.analyzer import AnomalyDetector
from spend_tracker.core import TrackerEngine
from spend_tracker.models import Campaign
from spend_tracker.notifier import AlertNotifier
from spend_tracker.report import ReportGenerator

logger = logging.getLogger(__name__)


@click.group()
@click.option("--config", "-c", default="config.yaml", help="Path to config YAML file")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose debug logging")
@click.version_option(__version__)
@click.pass_context
def cli(ctx: click.Context, config: str, verbose: bool) -> None:
    """Ad Spend Tracker — real-time ad spend monitoring & anomaly detection."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["verbose"] = verbose


@cli.command()
@click.option("--campaign", default="all", help="Campaign ID or 'all'")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.pass_context
def track(ctx: click.Context, campaign: str, json_output: bool) -> None:
    """Poll campaigns and display current spend."""
    engine = TrackerEngine(config_path=ctx.obj["config_path"])

    async def _run() -> None:
        if campaign == "all":
            results = await engine.poll_all_campaigns()
        else:
            spend = await engine.poll_campaign(campaign)
            results = {campaign: spend} if spend else {}

        if not results:
            click.echo("No spend data found. Check your config and API credentials.")
            return

        if json_output:
            import json

            data = {
                cid: {
                    "campaign_id": s.campaign_id,
                    "campaign_name": s.campaign_name,
                    "amount": s.amount,
                    "currency": s.currency,
                    "impressions": s.impressions,
                    "clicks": s.clicks,
                    "cpm": s.cpm,
                    "cpc": s.cpc,
                    "timestamp": s.timestamp.isoformat(),
                }
                for cid, s in results.items()
                if s is not None
            }
            click.echo(json.dumps(data, indent=2))
        else:
            click.echo("\n📊 Ad Spend Tracker — Live Spend\n")
            total = 0.0
            for cid, spend in results.items():
                if spend is None:
                    continue
                name = spend.campaign_name or cid
                click.echo(
                    f"  • {name:<40} ${spend.amount:>8.2f}  "
                    f"(imps: {spend.impressions:>6}, clicks: {spend.clicks:>4})"
                )
                total += spend.amount
            click.echo(f"\n  {'─' * 60}")
            click.echo(f"  {'Total':<40} ${total:>8.2f}")
            click.echo(f"  Polled at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

    asyncio.run(_run())


@cli.command()
@click.option("--check-anomalies", is_flag=True, help="Run anomaly detection")
@click.option("--send", "send_alerts", is_flag=True, help="Actually send alerts via Telegram")
@click.pass_context
def alert(ctx: click.Context, check_anomalies: bool, send_alerts: bool) -> None:
    """Check budget thresholds and detect anomalies."""
    engine = TrackerEngine(config_path=ctx.obj["config_path"])
    notifier = AlertNotifier()

    # Configure notifier from engine config
    telegram_cfg = engine.config.get("telegram", {})
    if telegram_cfg.get("bot_token") and telegram_cfg.get("chat_id"):
        notifier.configure(
            bot_token=telegram_cfg["bot_token"],
            chat_id=telegram_cfg["chat_id"],
        )

    async def _run() -> None:
        click.echo("🔍 Checking spend thresholds...")
        results = await engine.poll_all_campaigns()

        if not results:
            click.echo("No spend data to check.")
            return

        all_alerts: list = []

        # Budget threshold alerts
        budget_alerts = engine.check_thresholds(results)
        all_alerts.extend(budget_alerts)

        # Account cap
        total_spend = sum(s.amount for s in results.values())
        cap_alert = engine.check_daily_account_cap(total_spend)
        if cap_alert:
            all_alerts.append(cap_alert)

        # Anomaly detection
        if check_anomalies:
            click.echo("🔬 Running anomaly detection...", err=True)
            detector = AnomalyDetector()
            anomaly_alerts = detector.detect_anomalies(results)
            all_alerts.extend(anomaly_alerts)

        if not all_alerts:
            click.echo("✅ No alerts triggered. All campaigns within thresholds.")
            return

        click.echo(f"\n⚠️  {len(all_alerts)} alert(s) triggered:\n")
        for a in all_alerts:
            emoji = "🚨" if a.severity.value == "critical" else "⚠️" if a.severity.value == "warning" else "ℹ️"
            click.echo(f"  {emoji} [{a.severity.value.upper()}] {a.message}")

        if send_alerts and notifier.is_configured:
            click.echo("\n📨 Sending alerts via Telegram...")
            sent = await notifier.send_alerts(all_alerts)
            click.echo(f"  Sent {sent}/{len(all_alerts)} alerts successfully.")
        elif send_alerts:
            click.echo("\n⚠️  Telegram not configured. Set telegram.bot_token and chat_id in config.")

    asyncio.run(_run())


@cli.command()
@click.option("--type", "report_type", default="daily", type=click.Choice(["daily", "weekly"]),
              help="Report type")
@click.pass_context
def report(ctx: click.Context, report_type: str) -> None:
    """Generate a daily or weekly spend report."""
    engine = TrackerEngine(config_path=ctx.obj["config_path"])

    async def _run() -> None:
        click.echo(f"📊 Generating {report_type} report...", err=True)

        results = await engine.poll_all_campaigns()
        campaign_lookup: dict[str, Campaign] = {
            cid: c for cid, c in
            ((cid, engine.get_campaign(cid)) for cid in results)
            if c is not None
        }

        generator = ReportGenerator()
        generator.record_spends(list(results.values()))

        if report_type == "daily":
            output = generator.generate_daily_report(
                results, campaigns=campaign_lookup
            )
        else:
            output = generator.generate_weekly_report(
                results, campaigns=campaign_lookup
            )

        click.echo("")
        click.echo(output)

    asyncio.run(_run())


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current system status — providers, config, spend totals."""
    engine = TrackerEngine(config_path=ctx.obj["config_path"])

    click.echo("\n🔧 Ad Spend Tracker — System Status\n")

    # Provider status
    click.echo("Providers:")
    if engine.providers:
        for name, provider in engine.providers.items():
            click.echo(f"  ✅ {provider.platform_name} (account: {provider.account_id})")
    else:
        click.echo("  ⚠️  No providers configured. Set meta.access_token and ad_account_id in config.")
    click.echo("")

    # Config overview
    cfg = engine.config
    click.echo("Configuration:")
    meta_cfg = cfg.get("meta", {})
    click.echo(f"  • Meta account: {meta_cfg.get('ad_account_id', 'not set')}")
    click.echo(f"  • Meta API token: {'set' if meta_cfg.get('access_token') else 'not set'}")

    telegram_cfg = cfg.get("telegram", {})
    click.echo(f"  • Telegram bot: {'set' if telegram_cfg.get('bot_token') else 'not set'}")
    click.echo(f"  • Telegram chat: {telegram_cfg.get('chat_id', 'not set')}")

    thresholds = cfg.get("thresholds", {})
    click.echo(f"  • Daily soft cap: ${thresholds.get('daily_soft_cap', 100.0):.2f}")
    click.echo(f"  • Daily hard cap: ${thresholds.get('daily_hard_cap', 150.0):.2f}")
    click.echo(f"  • Spike threshold: {thresholds.get('spike_pct', 50.0)}%")
    click.echo(f"  • Anomaly z-score: {thresholds.get('anomaly_zscore', 2.5)}")

    click.echo("")
    click.echo("Budget Profiles:")
    for cid, budget in engine._budgets.items():  # type: ignore[attr-defined]
        if cid == "__default__":
            click.echo(f"  • Default: soft=${budget.soft_cap}, hard=${budget.hard_cap}")
        else:
            click.echo(f"  • {cid}: soft=${budget.soft_cap}, hard=${budget.hard_cap}")

    click.echo("")
    click.echo(f"Last poll: {engine.total_spend_today:.2f} total spend tracked")


if __name__ == "__main__":
    cli()
