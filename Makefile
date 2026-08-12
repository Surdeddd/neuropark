# pytest ставится в локальный .venv через uv: в рантайме nn нужен только stdlib,
# dev-инструменты живут отдельно и в требования продукта не входят.
PYTEST = uv run --with pytest --python 3.12 pytest

.PHONY: check test lint types smoke smoke-fast

check: lint types test

lint:
	ruff check .

types:
	mypy --strict src

test:
	$(PYTEST) -m "not smoke" -q

# полный набор живых прогонов, включая TTS с холодным стартом MLX (до 15 минут)
smoke:
	$(PYTEST) -m smoke -v

# то же без многоминутных: транскрипт, скан, доктор, цепочка
smoke-fast:
	$(PYTEST) -m "smoke and not slow" -v
