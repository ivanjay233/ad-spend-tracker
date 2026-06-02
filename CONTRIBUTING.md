# Contributing to Ad Spend Tracker

Thanks for your interest in contributing! This project is the "Boncos" system
for real-time ad spend monitoring. We welcome contributions of all kinds.

## Code of Conduct

Be excellent to each other. We're all here to build something useful.

## How to Contribute

### 1. Setup

```bash
# Clone the repo
git clone https://github.com/ivanjay233/ad-spend-tracker.git
cd ad-spend-tracker

# Install dev dependencies
make dev

# Verify setup
make test
make lint
```

### 2. Create a Branch

```bash
git checkout -b feat/my-cool-feature
```

Branch naming conventions:
- `feat/*` — New features (new provider, detection method, CLI command)
- `fix/*` — Bug fixes
- `docs/*` — Documentation improvements
- `refactor/*` — Code refactoring (no behavioral changes)
- `test/*` — Adding or improving tests

### 3. Make Your Changes

#### Code Style

- Python 3.10+ type annotations on all function signatures
- Ruff-compatible formatting (run `make fmt`)
- MyPy strict mode passes (`make lint`)
- Docstrings: Google-style or descriptive one-liners

#### Adding a New Platform Provider

1. Create `spend_tracker/providers/newplatform.py`
2. Implement `BaseProvider` ABC
3. Register in `TrackerEngine._load_config()`
4. Add tests in `tests/test_providers/`

#### Adding a Detection Method

1. Add method to `AnomalyDetector` in `spend_tracker/analyzer.py`
2. Add corresponding `AlertType` enum in `models.py`
3. Wire it into `detect_anomalies()`
4. Add tests

### 4. Test Your Changes

```bash
# Run all tests
make test

# Run specific tests
python -m pytest tests/test_core.py -v -k "test_soft_cap"

# Check coverage
make test-coverage
```

All new code should have tests. Aim for 80%+ coverage on new modules.

### 5. Commit

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short description>

<optional body>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `ci`, `chore`, `perf`

Examples:
```
feat: add Google Ads provider with OAuth2 support
fix: correct spike detection off-by-one in rolling window
docs: add FAQ section to README
test: add tests for Budget model validation
```

### 6. Submit a Pull Request

1. Push your branch: `git push origin feat/my-cool-feature`
2. Open a PR against `main`
3. Ensure CI passes (lint, types, tests)
4. Request review from @ivanjay233

## Project Structure

```
ad-spend-tracker/
├── spend_tracker/          # Main package
│   ├── __init__.py         # Version info
│   ├── core.py             # TrackerEngine — polling, thresholds, alerts
│   ├── analyzer.py         # AnomalyDetector — z-score, IQR, spike
│   ├── notifier.py         # AlertNotifier — Telegram dispatch
│   ├── report.py           # ReportGenerator — daily/weekly summaries
│   ├── models.py           # Pydantic models
│   ├── cli.py              # Click command-line interface
│   └── providers/          # Ad platform integrations
│       ├── base.py         # Abstract BaseProvider
│       └── meta.py         # Meta Ads implementation
├── examples/
│   ├── config.yaml.example # Configuration reference
│   └── daily_monitor.py    # Continuous monitoring script
├── tests/
│   └── test_core.py        # Core engine tests
├── .github/workflows/      # CI pipeline
├── Makefile                # Dev task runner
├── pyproject.toml          # Package config & tool settings
└── README.md               # Project documentation
```

## Questions?

Open an issue or ping @ivanjay233 on Telegram.
