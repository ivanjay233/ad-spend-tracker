#!/usr/bin/env python3
"""Daily monitoring script — polls campaigns, detects anomalies, sends alerts.

This is the primary 'boncos' monitoring script. Run it as a cron job
or systemd timer to continuously track ad spend throughout the day.

Usage:
    python daily_monitor.py [--config path/to/config.yaml] [--interval 300]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone

from spend_tracker.analyzer import AnomalyDetector
from spend_tracker.core import TrackerEngine
from spend_tracker.notifier import AlertNotifier
from spend_tracker.report import ReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("daily_monitor")


class DailyMonitor:
    """Continuous ad spend monitoring with anomaly detection and alerts.

    Runs a polling loop that:
    1. Fetches current spend from all providers
    2. Checks budget thresholds
    3. Runs anomaly detection on historical data
    4. Sends alerts via Telegram
    5. Sleeps until next poll interval
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        interval: int = 300,
    ) -> None:
        self.config_path = config_path
        self.interval = interval
        self._shutdown = False

        # Initialize components
        self.engine = TrackerEngine(config_path=config_path)
        self.detector = AnomalyDetector()
        self.notifier = AlertNotifier()
        self.reporter = ReportGenerator()

        # Configure notifier from engine config
        telegram_cfg = self.engine.config.get("telegram", {})
        if telegram_cfg.get("bot_token") and telegram_cfg.get("chat_id"):
            self.notifier.configure(
                bot_token=telegram_cfg["bot_token"],
                chat_id=telegram_cfg["chat_id"],
            )

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame: object) -> None:
        """Handle shutdown signals gracefully."""
        logger.info("Received signal %d, shutting down...", signum)
        self._shutdown = True

    async def run_once(self) -> None:
        """Execute a single monitoring cycle."""
        logger.info("=== Monitoring cycle ===")

        # 1. Poll campaigns
        results = await self.engine.poll_all_campaigns()
        if not results:
            logger.warning("No spend data returned from providers.")
            return

        total_spend = sum(s.amount for s in results.values())
        logger.info("Total spend: $%.2f across %d campaigns", total_spend, len(results))

        # 2. Check budget thresholds
        budget_alerts = self.engine.check_thresholds(results)
        cap_alert = self.engine.check_daily_account_cap(total_spend)
        if cap_alert:
            budget_alerts.append(cap_alert)

        if budget_alerts:
            logger.warning("%d budget alert(s) triggered", len(budget_alerts))
            self.reporter.record_alerts(budget_alerts)

        # 3. Anomaly detection
        anomaly_alerts = self.detector.detect_anomalies(results)
        if anomaly_alerts:
            logger.warning("%d anomaly alert(s) detected", len(anomaly_alerts))
            self.reporter.record_alerts(anomaly_alerts)

        # 4. Record for reports
        self.reporter.record_spends(list(results.values()))

        # 5. Send alerts via Telegram
        all_alerts = budget_alerts + anomaly_alerts
        if all_alerts and self.notifier.is_configured:
            sent = await self.notifier.send_alerts(all_alerts)
            logger.info("Sent %d/%d alerts via Telegram", sent, len(all_alerts))
        elif all_alerts:
            logger.warning("Alerts triggered but Telegram not configured.")

        # 6. Send daily report at configurable time (simple heuristic)
        now = datetime.now(timezone.utc)
        if now.hour == 23 and now.minute < 5:
            logger.info("Generating end-of-day report...")
            campaigns = {
                cid: c for cid in results
                if (c := self.engine.get_campaign(cid)) is not None
            }
            report = self.reporter.generate_daily_report(results, campaigns=campaigns)
            await self.notifier.send_message(report)
            logger.info("Daily report sent.")

        logger.info("Cycle complete.")

    async def run_forever(self) -> None:
        """Run the monitoring loop indefinitely."""
        logger.info(
            "Starting DailyMonitor (config=%s, interval=%ds)",
            self.config_path, self.interval,
        )
        if self.notifier.is_configured:
            await self.notifier.send_message(
                "🤖 *Ad Spend Monitor Started*\n"
                f"Monitoring configured campaigns every {self.interval}s.\n"
                f"Config: {self.config_path}"
            )

        while not self._shutdown:
            try:
                await self.run_once()
            except Exception as exc:
                logger.exception("Error in monitoring cycle: %s", exc)

            if not self._shutdown:
                await asyncio.sleep(self.interval)

        logger.info("Monitor stopped.")
        if self.notifier.is_configured:
            await self.notifier.send_message("🛑 *Ad Spend Monitor Stopped*")


def main() -> None:
    """Entry point for the daily monitor script."""
    parser = argparse.ArgumentParser(
        description="Ad Spend Tracker — Daily Monitor"
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to configuration file",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=300,
        help="Polling interval in seconds (default: 300)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit (for cron jobs)",
    )
    args = parser.parse_args()

    monitor = DailyMonitor(config_path=args.config, interval=args.interval)

    if args.once:
        asyncio.run(monitor.run_once())
    else:
        asyncio.run(monitor.run_forever())


if __name__ == "__main__":
    main()
