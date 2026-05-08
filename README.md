# tezaurs

Latvian morphological analysis library — a complete Python port of the
[LU MII Java morphology engine](https://github.com/PeterisP/morphology) plus a
sentence-level disambiguator stack.

Matches Java's published tag accuracy (92.50% vs 92.8%, within seed variance)
and exceeds Java's POS accuracy (98.76% vs 98.2%) on a held-out 20% split of
the gold corpus.

## Install

```bash
pip install -e .
```

For development:

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

## Components

| Module                  | LOC   | Role                                                |
|-------------------------|-------|-----------------------------------------------------|
| `analyzer.py`           | 1300  | Lemma analysis, prefix stripping, guessing          |
| `mijas.py`              | 2080  | Stem alternations (76 mija handlers, two directions) |
| `inflector.py`          |  190  | Forward generation with negation                    |
| `crf_tagger.py`         |  580  | Sentence-level disambiguator (CRF + per-POS LR)     |
| `markup.py`             |  230  | Position-tag emission and parsing                   |
| `attributes.py`         |  260  | Tagset + attribute matcher                          |
| `paradigm.py`           |  240  | Paradigm + endings (LV+LTG, 109 paradigms)          |
| `lexicon.py`            |  180  | Lazy-indexed Parquet lexicon                        |
| `trie.py`               |  510  | Tokenizer (12 hardcoded automata)                   |

## Accuracy (held-out 20%, 5-seed average)

| Metric | Java (LVTagger) | Python | Δ          |
|--------|----------------|--------|------------|
| Tag    | 92.8%          | 92.60% | within noise |
| Lemma  | not published  | 96.72% | —          |
| POS    | 98.2%          | 98.76% | **+0.56 pp** |

## Performance

| Metric                 | Value        |
|------------------------|--------------|
| Cold start             | 579 ms       |
| Sentence throughput    | ~1170 tok/s  |
| Peak memory            | ~475 MB      |
| Total package data     | 35 MB        |

## Reproducibility

```bash
python -m tools.benchmark              # full pipeline, 5-seed held-out
python -m tools.benchmark --no-overrides --no-viterbi  # ablations
pytest tests/                          # 41 unit + parity tests
```

## License

GPL-3.0-or-later. Same license as the upstream Java reference.

## Citation

See `paper/tezaurs_python_port.tex` (or the rendered PDF in releases) for the
full architecture write-up and benchmark methodology.
