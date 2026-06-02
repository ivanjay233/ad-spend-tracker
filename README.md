# Ad Spend Tracker

**Real-time advertising spend monitoring & anomaly detection** — the "Boncos" system.

Track your Meta Ads campaigns, detect spend spikes/anomalies in real-time, send Telegram alerts, and generate daily/weekly reports — all from the command line.

## The Problem

Advertisers running multiple campaigns lose thousands daily because:

- **Spend spikes** go unnoticed for hours before budget caps blow
- **Anomalous CPM/CPC** eats ROAS silently
- **No single dashboard** for real-time spend across campaigns
- **Alert fatigue** from noisy, unconfigurable thresholds

Ad Spend Tracker solves this with configurable thresholds, intelligent anomaly detection, and Telegram alerts that actually tell you what matters.

## Features

- **Real-time spend tracking** — poll Meta Ads API at configurable intervals
- **Anomaly detection** — statistical spike detection (z-score, IQR, rolling window)
- **Telegram alerts** — instant notifications for budget breaches, anomalies, daily caps
- **Daily & weekly reports** — auto-generated summaries via CLI or scheduled cron
- **Configurable thresholds** — per-campaign soft/hard caps, percentage deltas
- **CLI-first** — `ad-spend` command with `track`, `alert`, `report`, `status` subcommands
- **Extensible provider model** — start with Meta Ads, add Google/TikTok later
- **Pydantic validated** — all models type-checked and serializable

## Quick Start

```bash
# Install
pip install ad-spend-tracker

# Configure
cp config.yaml.example config.yaml
# Edit config.yaml with your Meta Ads credentials and Telegram bot token

# Track spend
ad-spend track --campaign all

# Check status
ad-spend status

# Generate a report
ad-spend report --type daily

# Run anomaly detection
ad-spend alert --check-anomalies
```

### Docker

```bash
docker build -t ad-spend-tracker .
docker run -v $(pwd)/config.yaml:/app/config.yaml ad-spend-tracker track
```

## Configuration

See [`config.yaml.example`](examples/config.yaml.example) for a full configuration reference.

Key settings:

| Setting | Description | Default |
|---------|-------------|---------|
| `meta.access_token` | Meta Ads API access token | — |
| `meta.ad_account_id` | Meta Ads account ID (`act_XXXXX`) | — |
| `telegram.bot_token` | Telegram bot token from BotFather | — |
| `telegram.chat_id` | Target chat/channel ID | — |
| `thresholds.daily_soft_cap` | Soft budget cap per campaign (USD) | 100.0 |
| `thresholds.daily_hard_cap` | Hard budget cap per campaign (USD) | 150.0 |
| `thresholds.anomaly_zscore` | Z-score threshold for anomaly detection | 2.5 |
| `thresholds.spike_pct` | Percentage spike threshold | 50.0 |

## Alert Rules

Alerts fire when any of these conditions are met:

1. **Budget breach** — Campaign spend exceeds soft or hard cap
2. **Spike detection** — Spend jumps > `spike_pct` % compared to same window yesterday
3. **Anomaly score** — Z-score exceeds `anomaly_zscore` relative to trailing 7-day window
4. **Daily cap hit** — Account-level daily spend cap reached

All alerts are sent via Telegram with campaign name, current spend, threshold crossed, and timestamp.

## Examples

```python
from spend_tracker.core import TrackerEngine

engine = TrackerEngine(config_path="config.yaml")
results = engine.poll_all_campaigns()

for campaign_id, spend in results.items():
    print(f"{campaign_id}: ${spend:.2f}")
```

See [`examples/daily_monitor.py`](examples/daily_monitor.py) for a complete monitoring script.

## Development

```bash
# Setup
make install

# Run tests
make test

# Lint
make lint

# Run the tracker
make track
```

## License

MIT
