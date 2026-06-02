"""Anomaly detection for ad spend — detects spikes, boncos, and outliers.

Uses multiple statistical methods to detect unusual spend patterns:
- Z-score against trailing window
- IQR (interquartile range) for non-normal distributions
- Percentage spike vs. previous period
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional, Tuple

from spend_tracker.models import Alert, AlertSeverity, AlertType, Spend

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Detects spend anomalies using configurable statistical methods.

    Maintains a rolling window of historical spend data per campaign
    and compares new data points against historical baselines.
    """

    def __init__(
        self,
        window_size: int = 7,
        zscore_threshold: float = 2.5,
        spike_pct_threshold: float = 50.0,
        iqr_multiplier: float = 1.5,
    ) -> None:
        self.window_size = window_size
        self.zscore_threshold = zscore_threshold
        self.spike_pct_threshold = spike_pct_threshold
        self.iqr_multiplier = iqr_multiplier

        # Rolling windows: campaign_id -> deque of (timestamp, amount)
        self._history: Dict[str, Deque[Tuple[datetime, float]]] = defaultdict(
            lambda: deque(maxlen=window_size * 2)  # larger buffer for IQR
        )

    def record_spend(self, spend: Spend) -> None:
        """Record a spend data point into the rolling history.

        Args:
            spend: The spend data point to record.
        """
        self._history[spend.campaign_id].append((spend.timestamp, spend.amount))

    def record_spends(self, spends: List[Spend]) -> None:
        """Record multiple spend data points."""
        for spend in spends:
            self.record_spend(spend)

    def detect_anomalies(self, spends: Dict[str, Spend]) -> List[Alert]:
        """Run all detection methods against the current spend data.

        Args:
            spends: Current spend data keyed by campaign_id.

        Returns:
            List of anomaly alerts.
        """
        alerts: list[Alert] = []

        for campaign_id, spend in spends.items():
            self.record_spend(spend)

            # 1. Z-score anomaly detection
            zscore_alert = self._check_zscore(campaign_id, spend)
            if zscore_alert:
                alerts.append(zscore_alert)

            # 2. Percentage spike detection
            spike_alert = self._check_spike(campaign_id, spend)
            if spike_alert:
                alerts.append(spike_alert)

            # 3. IQR-based outlier detection (non-parametric)
            iqr_alert = self._check_iqr(campaign_id, spend)
            if iqr_alert:
                alerts.append(iqr_alert)

        return alerts

    def _check_zscore(self, campaign_id: str, spend: Spend) -> Optional[Alert]:
        """Detect anomaly using z-score vs trailing window mean."""
        history = self._history.get(campaign_id)
        if not history or len(history) < 3:
            return None

        amounts = [a for _, a in history]

        if len(amounts) < 2:
            return None

        mean = statistics.mean(amounts)
        std = statistics.pstdev(amounts) if len(amounts) > 1 else 0.0

        if std == 0.0:
            return None

        zscore = (spend.amount - mean) / std

        if abs(zscore) > self.zscore_threshold:
            direction = "spike" if zscore > 0 else "drop"
            logger.info(
                "Anomaly detected: %s z-score=%.2f (threshold=%.1f) %s=%.2f",
                campaign_id, zscore, self.zscore_threshold, direction, spend.amount,
            )
            return Alert(
                campaign_id=campaign_id,
                campaign_name=spend.campaign_name,
                alert_type=AlertType.ANOMALY_DETECTED,
                severity=AlertSeverity.WARNING,
                message=(
                    f"📊 ANOMALY ({direction}): {spend.campaign_name or campaign_id} "
                    f"z-score={zscore:.2f} (threshold: {self.zscore_threshold}) "
                    f"current: ${spend.amount:.2f}, mean: ${mean:.2f}"
                ),
                current_spend=spend.amount,
                threshold_value=self.zscore_threshold,
            )
        return None

    def _check_spike(self, campaign_id: str, spend: Spend) -> Optional[Alert]:
        """Detect spend spike by comparing to same window yesterday."""
        history = self._history.get(campaign_id)
        if not history or len(history) < 2:
            return None

        # Get the most recent amount before this one
        amounts = [a for _, a in history]
        if len(amounts) < 2:
            return None

        prev_amount = amounts[-2]
        if prev_amount == 0:
            return None

        pct_change = ((spend.amount - prev_amount) / prev_amount) * 100.0

        if pct_change >= self.spike_pct_threshold:
            logger.info(
                "Spike detected: %s %.1f%% (threshold=%.1f%%)",
                campaign_id, pct_change, self.spike_pct_threshold,
            )
            return Alert(
                campaign_id=campaign_id,
                campaign_name=spend.campaign_name,
                alert_type=AlertType.SPEND_SPIKE,
                severity=AlertSeverity.WARNING,
                message=(
                    f"📈 SPIKE: {spend.campaign_name or campaign_id} "
                    f"up {pct_change:.1f}% (threshold: {self.spike_pct_threshold}%) "
                    f"prev: ${prev_amount:.2f} → now: ${spend.amount:.2f}"
                ),
                current_spend=spend.amount,
                threshold_value=self.spike_pct_threshold,
            )
        return None

    def _check_iqr(self, campaign_id: str, spend: Spend) -> Optional[Alert]:
        """Detect outlier using interquartile range method (robust to non-normal)."""
        history = self._history.get(campaign_id)
        if not history or len(history) < 4:
            return None

        amounts = sorted(a for _, a in history)
        if len(amounts) < 4:
            return None

        n = len(amounts)
        q1 = amounts[n // 4]
        q3 = amounts[(3 * n) // 4]
        iqr = q3 - q1

        if iqr == 0:
            return None

        lower_bound = q1 - self.iqr_multiplier * iqr
        upper_bound = q3 + self.iqr_multiplier * iqr

        if spend.amount > upper_bound:
            return Alert(
                campaign_id=campaign_id,
                campaign_name=spend.campaign_name,
                alert_type=AlertType.ANOMALY_DETECTED,
                severity=AlertSeverity.WARNING,
                message=(
                    f"📊 IQR OUTLIER: {spend.campaign_name or campaign_id} "
                    f"${spend.amount:.2f} exceeds upper bound ${upper_bound:.2f} "
                    f"(Q1=${q1:.2f}, Q3=${q3:.2f}, IQR=${iqr:.2f})"
                ),
                current_spend=spend.amount,
                threshold_value=upper_bound,
            )
        elif spend.amount < lower_bound:
            return Alert(
                campaign_id=campaign_id,
                campaign_name=spend.campaign_name,
                alert_type=AlertType.ANOMALY_DETECTED,
                severity=AlertSeverity.INFO,
                message=(
                    f"📉 IQR DROP: {spend.campaign_name or campaign_id} "
                    f"${spend.amount:.2f} below lower bound ${lower_bound:.2f}"
                ),
                current_spend=spend.amount,
                threshold_value=lower_bound,
            )
        return None

    def get_history(self, campaign_id: str) -> List[Tuple[datetime, float]]:
        """Get the rolling history for a campaign."""
        return list(self._history.get(campaign_id, []))

    def clear_history(self, campaign_id: Optional[str] = None) -> None:
        """Clear history for a specific campaign or all campaigns."""
        if campaign_id:
            self._history.pop(campaign_id, None)
        else:
            self._history.clear()

    def status_summary(self) -> Dict[str, dict]:
        """Get a summary of tracked campaigns and their history sizes.

        Returns:
            Dict of campaign_id -> {record_count, last_seen, mean_spend}
        """
        summary: dict[str, dict] = {}
        for campaign_id, history in self._history.items():
            if history:
                amounts = [a for _, a in history]
                summary[campaign_id] = {
                    "record_count": len(history),
                    "last_seen": history[-1][0].isoformat(),
                    "mean_spend": statistics.mean(amounts),
                    "min_spend": min(amounts),
                    "max_spend": max(amounts),
                }
        return summary
