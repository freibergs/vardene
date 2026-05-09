# Common dev tasks for Vārdene. Run `make help` for the full list.

PYTHON ?= .venv/bin/python
PIP    ?= .venv/bin/pip
PORT   ?= 5000

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help message
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: install
install: ## Install in editable mode with all extras
	$(PIP) install -e '.[dev,api,tools]'

.PHONY: test
test: ## Run the unit suite (65 tests)
	$(PYTHON) -m pytest tests/test_unit.py -v

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	$(PYTHON) -m pytest tests/test_unit.py --cov=vardene --cov-report=term --cov-report=html

.PHONY: lint
lint: ## Run ruff
	$(PYTHON) -m ruff check vardene tests examples

.PHONY: lint-fix
lint-fix: ## Run ruff with auto-fix
	$(PYTHON) -m ruff check vardene tests examples --fix

.PHONY: typecheck
typecheck: ## Run mypy
	$(PYTHON) -m mypy vardene

.PHONY: ci-local
ci-local: lint typecheck test ## Run the same checks CI runs

.PHONY: bench
bench: ## Run the 5-seed held-out accuracy benchmark
	$(PYTHON) -m tools.benchmark

.PHONY: bench-ablations
bench-ablations: ## Run benchmark + the three documented ablations
	$(PYTHON) -m tools.benchmark
	$(PYTHON) -m tools.benchmark --no-overrides
	$(PYTHON) -m tools.benchmark --no-viterbi

.PHONY: api
api: ## Start the Flask demo server (default port 5000)
	$(PYTHON) -m vardene.api --port $(PORT)

.PHONY: paper
paper: ## Recompile the paper PDF (twice, to resolve cross-references)
	cd paper && pdflatex -interaction=nonstopmode vardene_python_port.tex > /dev/null
	cd paper && pdflatex -interaction=nonstopmode vardene_python_port.tex > /dev/null
	cd paper && rm -f *.aux *.log *.out *.bbl *.blg *.toc *.fdb_latexmk *.fls *.synctex.gz

.PHONY: build
build: ## Build the wheel + sdist into dist/
	$(PIP) install --upgrade build
	$(PYTHON) -m build

.PHONY: examples
examples: ## Run all three example scripts
	$(PYTHON) examples/01_analyse_a_word.py
	$(PYTHON) examples/02_tag_a_sentence.py "Māte sēd uz galda."
	$(PYTHON) examples/03_inflect_phrase.py "sarkanā māja"

.PHONY: clean
clean: ## Remove build artefacts and caches
	rm -rf build dist *.egg-info
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find paper -maxdepth 1 \( -name "*.aux" -o -name "*.log" -o -name "*.out" \) -delete 2>/dev/null || true
