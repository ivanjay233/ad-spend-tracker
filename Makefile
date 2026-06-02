.PHONY: install dev test lint fmt clean track report run

# Installation
install:
	pip install -e .

dev:
	pip install -e ".[dev]"

# Testing
test:
	python -m pytest tests/ -v --cov=spend_tracker --cov-report=term-missing

test-coverage:
	python -m pytest tests/ -v --cov=spend_tracker --cov-report=html
	@echo "Coverage report: open htmlcov/index.html"

# Linting
lint:
	ruff check spend_tracker/ tests/ examples/
	mypy spend_tracker/ --ignore-missing-imports

fmt:
	ruff format spend_tracker/ tests/ examples/

# Cleanup
clean:
	rm -rf build/ dist/ *.egg-info/ __pycache__/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf .coverage htmlcov/ .mypy_cache/ .ruff_cache/

# Run commands
track:
	ad-spend track

alert:
	ad-spend alert --check-anomalies

report:
	ad-spend report --type daily

status:
	ad-spend status

# Docker
docker-build:
	docker build -t ad-spend-tracker .

docker-run:
	docker run -v $(PWD)/config.yaml:/app/config.yaml ad-spend-tracker track

# Continuous monitoring (background)
run:
	python examples/daily_monitor.py --config config.yaml --interval 300
