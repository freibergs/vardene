<div align="center">

# tezaurs

**Latvian morphological analysis library — a complete Python port of the LU MII Java engine**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/license-GPL%20v3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Tests](https://img.shields.io/badge/tests-41%2F41%20passing-brightgreen.svg)](#testing)
[![Tag accuracy](https://img.shields.io/badge/tag%20accuracy-92.60%25-brightgreen.svg)](#accuracy)
[![POS accuracy](https://img.shields.io/badge/POS%20accuracy-98.76%25-brightgreen.svg)](#accuracy)
[![Throughput](https://img.shields.io/badge/throughput-1170%20tok%2Fs-brightgreen.svg)](#performance)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

*Matches Java tag accuracy within seed variance · Exceeds Java POS accuracy by +0.56 pp · 44% smaller source · 8× smaller data · 2.6× faster cold start*

</div>

---

## Overview

A complete Python port of [github.com/PeterisP/morphology](https://github.com/PeterisP/morphology) — the engine behind [api.tezaurs.lv](https://api.tezaurs.lv), the public Latvian morphology API used by Latvian NLP researchers and downstream tooling. This port reproduces every algorithmic component of the upstream Java engine (Mijas, Trie, Lexicon, Paradigm, Analyzer, Inflector, MarkupConverter) **plus** ships a sentence-level disambiguator stack that closes the gap to the production CRF tagger.

> "Funkcija aprakstā saka 'kā', tabula saka 'kas'."

That principle drives the architecture: where Java has 60 elif-chained mija-handler functions, the Python port factors stem-alternation rules into shared `SuffixRule` tables consumed by tiny case wrappers — the linguistic data is data, the dispatcher is engine.

## Highlights

- 🎯 **Java-parity accuracy** on held-out 5-seed evaluation
- 🚀 **1170 tok/s** sentence-level throughput (single CPU core)
- 📦 **34 MB total package data** (vs ~75 MB upstream XML, 8× compression)
- ⚡ **579 ms cold start** (vs ~1.5 s JVM warmup, 2.6× faster)
- 🪶 **5193 LOC engine** (vs 9316 Java, 44% smaller)
- 🐍 **Pure Python**, no JVM, no Maven — just `pip install`

## Install

```bash
pip install -e .
```

For development (tests, training tools, ruff):

```bash
pip install -e '.[dev,tools]'
```

## Quick start

```python
from tezaurs.analyzer import Analyzer

a = Analyzer()
a.enable_guessing = True

# Single-word analysis — returns all candidate readings
result = a.analyze("rakstu")
for wf in result.wordforms:
    print(wf.lexeme.lemma, wf)

# Sentence-level analysis — applies CRF + classifier + Viterbi disambiguation
results = a.analyze_sentence(["Māte", "sēd", "uz", "galda", "."])
for r in results:
    print(r.token, "→", r.wordforms[0])
```

```python
from tezaurs.inflector import Inflector

inf = Inflector()
forms = inf.inflect("rakt")  # 536 forms incl. negation, debitive, all participles
```

## Accuracy

Held-out 20% split, 5-seed average ($n \approx 3{,}500$ tokens per seed):

| Metric | **tezaurs (Python)** | LVTagger (Java) | Δ |
|---|---|---|---|
| Tag | **92.60 %** | 92.8 % | within seed variance |
| Lemma | **96.72 %** | not published | — |
| **POS** | **98.76 %** | 98.2 % | **+0.56 pp** ✓ |

Two of five seeds exceed Java's 92.8% tag mark (best seed: 92.89%). See [`paper/tezaurs_python_port.pdf`](paper/tezaurs_python_port.pdf) for full methodology and ablation.

## Performance

| Metric | Value |
|---|---|
| Cold start (`Analyzer()` init) | 579 ms |
| Sentence-level throughput | ~1170 tok/s |
| Sentence-level latency | ~14 ms / sentence |
| Peak resident memory | 475 MB |
| Total package data | 34 MB |

Benchmarked on Apple M1 Pro, single CPU core.

## Architecture

| Module | LOC | Role |
|---|---:|---|
| [`analyzer.py`](tezaurs/analyzer.py) | 1289 | Lemma analysis · prefix stripping · guessing · per-form/per-lemma overrides |
| [`mijas.py`](tezaurs/mijas.py) | 1133 | Latvian stem alternations (analysis + inflection directions) |
| [`mijas_ltg.py`](tezaurs/mijas_ltg.py) | 762 | Latgalian stem alternations |
| [`mijas_dsl.py`](tezaurs/mijas_dsl.py) | 81 | Shared `SuffixRule` data + `_apply_first` / `_apply_all` helpers |
| [`crf_tagger.py`](tezaurs/crf_tagger.py) | 527 | POS CRF + 4-char subtag CRF + per-POS LR + Viterbi rescoring |
| [`trie.py`](tezaurs/trie.py) | 510 | Tokenizer (12 hardcoded automata) |
| [`attributes.py`](tezaurs/attributes.py) | 260 | Tagset + multi-value attribute matcher |
| [`paradigm.py`](tezaurs/paradigm.py) | 238 | 109 paradigms (LV + LTG), 5938 endings |
| [`markup.py`](tezaurs/markup.py) | 231 | Position-tag emit / parse |
| [`inflector.py`](tezaurs/inflector.py) | 188 | Forward generation with negation, debitive, participles |
| [`lexicon.py`](tezaurs/lexicon.py) | 182 | Lazy-indexed Parquet lexicon (411k lexemes) |
| [`statistics.py`](tezaurs/statistics.py) | 100 | Additive ranking ($0.1 + ef + lf \cdot 1000$) |

The disambiguator pipeline is layered — POS CRF predicts the POS character, a per-POS log-linear classifier (sparse CSR weights, 16 MB on disk) predicts the full tag, a tag-bigram Viterbi pass enforces local consistency, and a high-confidence per-form corpus override layer (3{,}889 entries, ≥5 occurrences with ≥85% concentration) bypasses the engine's candidate-set ceiling for the +3 pp jump that gets the port to Java parity.

## HTTP API + demo UI

A minimal Flask app exposes the engine over HTTP and includes a single-page
demo UI:

```bash
pip install -e '.[api]'
python -m tezaurs.api          # http://127.0.0.1:5000
```

Endpoints (parity with the Java `api.tezaurs.lv` service where the underlying
engine supports it; 6 specialised routes return 501 until their upstream
modules are ported):

| Route | Description |
|---|---|
| `GET /api/analyze/<word>` | Single-word analysis (LV attributes) |
| `GET /api/analyze/en/<word>` | Same with English attribute names |
| `GET /api/analyzesentence/<query>` | Per-token analysis with sentence context |
| `GET /api/morphotagger/<query>` | Sentence-level disambiguation (top reading per token) |
| `GET /api/tokenize/<query>` · `POST /api/tokenize` | Tokenisation |
| `GET /api/v1/inflections/<lemma>` | All inflectional forms |
| `GET /api/v1/inflections/<lemma>?paradigm=NAME` | With explicit paradigm |
| `GET /api/v1/inflections/<lemma>?paradigm=&stem1=&stem2=&stem3=` | Verb-1 with explicit stems |
| `GET /api/inflect/json/<lemma>` · `/json/<lang>/<lemma>` | Format- and language-selectable inflection |
| `GET /api/health` | Liveness probe |

Pending (501 Not Implemented): `/api/verbs`, `/api/neverbs`,
`/api/suitable_paradigm`, `/api/inflect_people`, `/api/inflect_phrase`,
`/api/normalize_phrase` — these wrap upstream modules (verb-valency tool,
paradigm scorer, person-name inflector, multi-word entity inflection)
that have not yet been ported.

## Reproducibility

```bash
# Run the full test suite (41 tests)
pytest tests/

# Reproduce paper Table 2 — 5-seed held-out evaluation
python -m tools.benchmark

# Ablations
python -m tools.benchmark --no-overrides    # disable per-form corpus overrides
python -m tools.benchmark --no-viterbi      # disable bigram Viterbi pass
python -m tools.benchmark --train           # evaluate on full train corpus (overfit signal)
```

## Citation

If you use this in academic work, please cite the accompanying technical report:

```bibtex
@techreport{freibergs2026tezaurs,
  title  = {A Python Port of the LU MII Latvian Morphological Analyser:
            Performance, Accuracy, and Engineering Trade-offs},
  author = {Freibergs, Rihards Aleksandrs},
  year   = {2026},
  note   = {GPL-3.0, available at \url{https://github.com/<owner>/tezaurs}}
}
```

The full PDF lives in [`paper/tezaurs_python_port.pdf`](paper/tezaurs_python_port.pdf).

## Credits

This port stands on the work of Pēteris Paikens and the LU MII AI Lab (the original [Java morphology engine](https://github.com/PeterisP/morphology)) and the LVTagger contributors (the gold-standard `train.txt` corpus). The port itself was written, trained, and benchmarked by Rihards Aleksandrs Freibergs.

## License

GPL-3.0-or-later. Same license as the upstream Java reference. See [`LICENSE`](LICENSE) for the full text.

## Contributing

Pull requests welcome. Please run `pytest tests/` (41 tests) and `python -m tools.benchmark` (5-seed held-out parity) before submitting; both should be green and within ±0.5 pp of the published numbers.
