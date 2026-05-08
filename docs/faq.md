# Frequently Asked Questions

## Why "Vārdene"?

It's the Latvian word for "wordbook" (`vārds` = word, `-ene` = nominal-derivation suffix), evoking *Tēzaurs* but emphasising the word-form rather than dictionary-entry orientation. The Python package, file paths, and command-line tools all use the ASCII form `vardene` because Python identifiers and PyPI names cannot contain non-ASCII characters; the display name everywhere else (README, paper, UI, citation) is **Vārdene**.

## How is this different from UDPipe / Stanza for Latvian?

UDPipe and Stanza ship a single end-to-end neural pipeline trained on the Latvian Universal Dependencies treebank. They expose Universal Dependencies features per token and treat morphology as a black box.

Vārdene is a port of the LU MII Latvian morphology engine, which is **rule + lexicon based**, has 411k lexemes, supports forward generation (inflect a lemma into all forms), and exposes paradigm-suitability scoring, multi-word phrase declension, and personal-name inflection. The disambiguator on top of it (CRF + per-POS LR + Viterbi) achieves 92.51 % tag accuracy on the LVTagger gold corpus.

Pick UDPipe / Stanza if you want UD-style features and a single model. Pick Vārdene if you need:
- Full inflectional paradigms for a lemma
- Multi-word phrase declension (`sarkanā māja` → all 5 cases)
- Personal-name paradigm tables
- Latvian-specific tag set (`Vārdšķira`, `Locījums`, `Skaitlis`, `Dzimte`, ...)
- Drop-in replacement for `api.tezaurs.lv` services

## Why is `plkst.` tokenised as one token but `etc.` as two?

The tokenizer registers every multi-character lemma in the lexicon that contains a space, period, slash, apostrophe, or digit as a tokenizer-trie exception. There are 1,622 such entries: `plkst.`, `u.c.`, `t.i.`, `A/S`, etc. `etc.` is not in the Latvian lexicon, so the period splits off normally.

To register your own abbreviations:

```python
from vardene.splitting import build_trie, set_master_trie

set_master_trie(build_trie(["mr.foo", "Acme.Corp"]))
```

## Why does `kaķis` return three readings instead of upstream's two?

Vārdene's lexicon registers `kaķis` under both `noun-2a` (with mija) and `noun-2b` (without mija); upstream registers it only under `noun-2b`. Both are linguistically defensible. We treat this as a known, intentional divergence rather than a bug — see [paper Section "Where Python wins / loses"](../paper/vardene_python_port.pdf).

## Can I use Vārdene from JavaScript / Go / Rust?

Yes — run the Flask HTTP service and call it over HTTP:

```bash
pip install -e '.[api]'
python -m vardene.api  # http://127.0.0.1:5000
```

Every endpoint returns raw UTF-8 JSON. The full route table is in [README.md → HTTP API](../README.md#http-api).

## How do I retrain the disambiguator on my own corpus?

The training scripts live in `tools/`:

```bash
python -m tools.train_crf_pos          # POS CRF (13 classes, ~13 s)
python -m tools.train_crf_subtag 4     # 4-character subtag CRF (~4 min)
python -m tools.train_per_pos_classifier  # per-POS log-linear classifiers (~45 s)
python -m tools.train_disambiguator    # form-level corpus override table
```

Each script reads `tools/data/train.txt` (the LVTagger gold corpus) and writes its model into `vardene/data/`. To swap in your own corpus, replace `train.txt` with a file in the same TSV format (`token<TAB>tag<TAB>lemma`, one token per line, blank line between sentences).

## How do I cite this in academic work?

The repo includes a [`CITATION.cff`](../CITATION.cff) so GitHub renders a "Cite this repository" button. The full BibTeX is in [README → Citation](../README.md#citation). The accompanying technical report is at [`paper/vardene_python_port.pdf`](../paper/vardene_python_port.pdf).

## Does it work for Latgalian?

Latgalian (LTG) paradigms are present in the lexicon and the Mijas engine (`mijas_ltg.py`, 802 LOC). Generation works. The **disambiguator is Latvian-only**, however — it was trained on `train.txt`, which contains no Latgalian text. We do not report LTG accuracy figures.

## Why is the cold start so slow on the first sentence?

The disambiguator stack (POS CRF + per-POS LR + Viterbi transition matrix) lazy-loads on the first sentence call to keep `Analyzer()` initialisation cheap. Pure word-level analysis (`analyze("word")`) does not load the disambiguator and is fast (~250 ms cold + analysis time). If you need predictable latency, call `analyzer.analyze_sentence([])` once at startup to force the lazy load.

## Will there be a PyPI release?

Soon. The package builds with `hatchling` and the `pyproject.toml` is PyPI-ready (license, classifiers, type marker). Until the first release, install from source:

```bash
pip install git+https://github.com/freibergs/vardene.git
```
