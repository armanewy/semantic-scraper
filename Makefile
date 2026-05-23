.PHONY: install test lint demo mutate benchmark clean

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	ruff check src tests

demo:
	semscrape extract examples/product.yml examples/product_v1.html --policy ranker-local --values-only
	semscrape extract examples/product.yml examples/product_v2.html --policy ranker-local --values-only

mutate:
	rm -rf mutations
	semscrape mutate examples/product_v1.html --out mutations --n 20 --seed 7

benchmark:
	semscrape benchmark examples/product.yml examples/product_v1.html examples/product_v2.html --no-llm

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info mutations
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
