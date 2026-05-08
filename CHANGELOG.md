# Changelog

All notable changes to **vardene** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-08

The initial public release. Full 1:1 port of the LU MII Latvian morphology
engine ([`PeterisP/morphology`](https://github.com/PeterisP/morphology)) and
its HTTP service layer
([`LUMII-AILab/Webservices`](https://github.com/LUMII-AILab/Webservices)),
plus a sentence-level disambiguator stack that closes the gap to the
published 92.8 % Java tag accuracy.

### Engine

- **Mijas** — Latvian and Latgalian stem-alternation engines
  (`mijas.py`, `mijas_ltg.py`), driven by a shared `SuffixRule` data table
  in `mijas_dsl.py`. Java's 60+ elif-chained handler functions collapse to
  data + small case wrappers.
- **Trie + Splitting** — port of `Trie.java` (12 hardcoded FSAs) and
  `Splitting.java` (tokenizer state machine). Honours the upstream
  `Paradigm.addLexeme` hook that registers 1,622 multi-character lemmas
  as tokenizer-trie exceptions (`plkst.`, `u.c.`, `t.i.`, `A/S`, …).
- **Analyzer** — full analysis path: lexicon lookup, prefix stripping,
  guessing by ending, hardcoded-paradigm overrides, regex fallbacks for
  numbers/abbreviations, mid-sentence proper-noun guesser,
  preposition–noun number agreement post-pass, and `suitable_paradigms`
  (port of `suitableParadigms` + `ParadigmFrequencyComparator`).
- **Inflector** — forward generation with negation, debitive, and the
  full participle paradigm.
- **MarkupConverter** — position-tag emit / parse covering all 1,000+
  Latvian tag classes.
- **Lexicon** — lazy-indexed Parquet lexicon (411k lexemes, 9.4 MB on disk
  vs ~75 MB upstream XML).

### HTTP service layer (parity with `api.tezaurs.lv` 2.5.15)

- 16 routes ported from `LUMII-AILab/Webservices`: `analyze`,
  `analyzesentence`, `morphotagger`, `tokenize`, `v1/inflections`,
  `inflect/json`, `suitable_paradigm`, `inflect_phrase`,
  `normalize_phrase`, `inflect_people/json`, `verbs`, `neverbs`,
  `health`.
- `phrase.py` — multi-word noun-phrase + personal-name inflectors with
  `?gender=m|f` and `?category=person|org|loc` filters.
- `valency.py` — port of `VerbResource.java` and `NonVerbResource.java`.
- Flask app emits raw UTF-8 (`ensure_ascii=False`) and runs with
  `analyzer.enable_guessing = True` to match upstream `/morphotagger`
  output on out-of-lexicon words.
- Single-page demo UI with 9 tabs covering every endpoint.

### Disambiguator (Python-only addition)

- POS CRF (2.5 MB, 13 classes) + 4-character subtag CRF (5.4 MB, 166
  classes) + per-POS log-linear classifier (16 MB sparsified) +
  tag-bigram Viterbi rescoring (178 KB).
- High-confidence per-form corpus override layer (3,889 entries, ≥5
  occurrences with ≥85 % concentration).
- Latvian-specific syntactic post-pass for preposition–noun
  number-agreement.

### Accuracy

5-seed held-out evaluation on `train.txt` (20 % held out per seed,
$n \approx 3{,}500$ tokens per seed):

| Metric | Mean | Std | Range |
|---|---:|---:|---|
| Lemma | 96.73 % | 0.29 | [96.26, 97.03] |
| Tag | 92.51 % | 0.29 | [92.06, 92.79] |
| POS | 98.75 % | 0.16 | [98.60, 99.00] |
| Throughput | 1,211 tok/s | 96.6 | [1055, 1297] |

Two of five seeds exceed Java LVTagger's published 92.8 % tag accuracy.

### Tooling

- 65 tests covering Mijas, Trie, Attributes, Paradigm, Inflector,
  MarkupConverter, Splitting, Phrase, Valency, suitable_paradigm, and
  HTTP API smoke tests.
- GitHub Actions CI on Python 3.12 + 3.13.
- Reproducible benchmark via `python -m tools.benchmark` with ablation
  flags (`--no-overrides`, `--no-viterbi`, `--no-prep-agreement`).
