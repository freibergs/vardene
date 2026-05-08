# Contributing to vardene

Thanks for your interest in contributing. This guide covers the development workflow, code style, and what to verify before opening a pull request.

## Development setup

```bash
git clone https://github.com/freibergs/vardene.git
cd vardene
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,api]'
```

The package ships its trained models, lexicon (Parquet), tagset, paradigms, and override JSONs as package data — no separate "build the data" step is required for normal development. If you change `tools/extract_data.py` and need to regenerate the data files from upstream Java XML, you'll need a local clone of `PeterisP/morphology` at `./reference/`.

## Running the test suite

```bash
pytest tests/                                # 65 unit + parity tests
python -m tools.benchmark                    # 5-seed held-out evaluation (~30 s)
```

Both must be green before you submit a PR. The held-out evaluation should land within ±0.5 pp of the published numbers (Tag 92.51 ± 0.29, POS 98.75 ± 0.16, Lemma 96.73 ± 0.29).

## Code style

- **Lint:** `ruff check vardene tests` must pass clean. Configuration is in `pyproject.toml`.
- **Type hints:** prefer `from __future__ import annotations` at the top of new modules; use modern PEP 604 union syntax (`X | Y`) and built-in generics (`list[str]`, `dict[str, int]`).
- **Comments:** the project favours minimal comments. Identifiers should be self-documenting; comments are reserved for non-obvious *why* (hidden constraints, workarounds, references to specific Java upstream behaviour). Don't write docstrings that just restate the function name.
- **Latvian attribute names** are kept verbatim throughout the engine (`Vārdšķira`, `Locījums`, `Skaitlis`, etc.) so that parity testing against `api.tezaurs.lv` is trivial. Translation to English happens in a thin layer (`vardene/api/serialization.py`).

## What to verify before opening a PR

For changes to the **engine** (`vardene/*.py` excluding `api/`):

- [ ] `pytest tests/test_unit.py` passes
- [ ] `python -m tools.benchmark` is within ±0.5 pp of the published numbers
- [ ] Any new public function has a one-line docstring describing the *why*

For changes to the **HTTP API** (`vardene/api/*`):

- [ ] `pytest tests/test_unit.py::TestApi` passes
- [ ] If you add a new endpoint, A/B test it against `http://api.tezaurs.lv:8182/<route>` and document any divergence in the PR description
- [ ] If you add a new UI tab, verify it works in both light and dark mode (the CSS is `prefers-color-scheme` aware)

For changes to the **paper** (`paper/vardene_python_port.tex`):

- [ ] Recompile with `pdflatex -interaction=nonstopmode vardene_python_port.tex` (twice, to resolve cross-references)
- [ ] Commit both the `.tex` and the regenerated `.pdf`
- [ ] No new "Overfull \hbox" warnings in the log

## Known divergences from upstream

The port is byte-equal with `api.tezaurs.lv` on the canonical test cases, but there are a handful of intentional or data-driven differences. See [`paper/vardene_python_port.pdf`](paper/vardene_python_port.pdf), Section 6 ("Where Python wins / loses") for the catalogue. Don't try to "fix" any of these without a discussion in an issue first — most of them are linguistically defensible alternatives, not bugs.

## Reporting bugs

Please include:

- Python version and OS
- The exact input that triggered the bug
- The expected output (e.g. from `api.tezaurs.lv:8182`)
- The actual output from `vardene`
- Output of `pytest tests/test_unit.py -v` if any tests fail

## License

By contributing you agree that your contributions are licensed under the project's GPL-3.0-or-later license.
