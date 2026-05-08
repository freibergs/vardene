"""Build a form→(tag, lemma) preference table from the gold corpus.

The Java pipeline trains a CRF tagger on `train.txt`. We ship a simpler
form-keyed lookup: for each surface form, the most-frequent (tag, lemma)
pair from the corpus. The Analyzer uses this as a final disambiguation
tier — when our analyses include a wordform whose (tag, lemma) matches
the corpus preference, that wordform is moved to the top.

This is conceptually equivalent to a unigram tagger + lemmatizer trained on
the same corpus. Real CRF would add bigram/trigram context for ~3-5% more
accuracy; this gets us most of the way.

Run: `python -m tools.train_disambiguator`
Output: `tezaurs/data/form_disambiguation.json`
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = REPO_ROOT / "tools" / "data" / "train.txt"
DEFAULT_OUT = REPO_ROOT / "tezaurs" / "data" / "form_disambiguation.json"


def build_table(corpus_path: Path, min_count: int = 2) -> dict[str, list[str]]:
    """Returns `{form: [tag, lemma]}` keyed on the surface form, picking the
    most-frequent (tag, lemma) pair seen for that form. Forms appearing fewer
    than `min_count` times are dropped — they don't have enough signal."""
    by_form: dict[str, Counter] = {}
    with corpus_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("<"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            form, tag, lemma = parts[0], parts[1], parts[2]
            by_form.setdefault(form, Counter())[(tag, lemma)] += 1

    table: dict[str, list[str]] = {}
    for form, c in by_form.items():
        (top_tag, top_lemma), top_count = c.most_common(1)[0]
        if top_count < min_count:
            continue
        table[form] = [top_tag, top_lemma]
    return table


def main() -> int:
    corpus = DEFAULT_CORPUS
    out = DEFAULT_OUT
    if len(sys.argv) > 1:
        corpus = Path(sys.argv[1])
    if len(sys.argv) > 2:
        out = Path(sys.argv[2])

    print(f"Training from {corpus}")
    table = build_table(corpus)
    print(f"  forms: {len(table):,}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = out.stat().st_size / 1024
    print(f"  written: {out} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
