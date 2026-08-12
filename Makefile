# pytest is pulled into a local .venv through uv: nn needs only stdlib at runtime,
# so dev tools stay out of the product's requirements.
# pytest ставится в локальный .venv через uv: в рантайме nn нужен только stdlib.
PYTEST = uv run --with pytest --python 3.12 pytest

.PHONY: help setup check test lint format types smoke smoke-fast hooks clean

help:
	@printf 'nn — make targets\n\n'
	@printf '  make setup        install: link the skill, detect tools, first scan\n'
	@printf '  make check        ruff + ruff format --check + mypy --strict + unit tests\n'
	@printf '  make test         unit tests only (no network, no subscriptions)\n'
	@printf '  make lint         ruff check\n'
	@printf '  make format       ruff format src tests\n'
	@printf '  make types        mypy --strict src\n'
	@printf '  make smoke-fast   live offline runs on real hardware (~30s)\n'
	@printf '  make smoke        plus TTS with a cold model start (up to 15 min)\n'
	@printf '  make hooks        install the git pre-commit hook\n'
	@printf '  make clean        drop caches and the local .venv\n'

setup:
	./install.sh

check: lint format-check types test

lint:
	ruff check .

format:
	ruff format src tests

format-check:
	ruff format --check src tests

types:
	mypy --strict src

test:
	$(PYTEST) -m "not smoke" -q

# Full set of live runs, including TTS with a cold MLX start (up to 15 minutes).
smoke:
	$(PYTEST) -m smoke -v

# Same minus the multi-minute ones: scan, transcript, bridge, doctor.
smoke-fast:
	$(PYTEST) -m "smoke and not slow" -v

hooks:
	@ln -sf ../../hooks/pre-commit .git/hooks/pre-commit
	@printf 'git pre-commit hook installed → hooks/pre-commit\n'
	@printf 'skip once with: git commit --no-verify\n'

clean:
	@rm -rf .venv .pytest_cache .mypy_cache .ruff_cache
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
	@printf 'caches and .venv removed\n'
