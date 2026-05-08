"""Parity tests vs the gold-standard corpus (`train.txt`) shipped with the
upstream LU MII project. Each line is `word\\ttag\\tlemma\\tID`; we sample N
words and check our analyzer's top wordform.

The gold corpus is what the upstream Java tagger was trained on, so 100%
parity is unrealistic without porting the statistical disambiguator. Our
target after all fixes: lemma ≥ 95%, tag ≥ 90% on a 1000-word sample.

Run: `pytest tests/parity.py -v` or just `python tests/parity.py`.
"""

from __future__ import annotations

import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vardene.analyzer import Analyzer
from vardene.markup import to_tag

CORPUS = Path(__file__).resolve().parent.parent / "tools" / "data" / "train.txt"


def load_corpus(path: Path = CORPUS) -> list[tuple[str, str, str]]:
    """Return a list of (word, tag, lemma) triples from the gold corpus."""
    rows: list[tuple[str, str, str]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("<"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            word, tag, lemma = parts[0], parts[1], parts[2]
            rows.append((word, tag, lemma))
    return rows


def sample_words(
    rows: list[tuple[str, str, str]], n: int, *, seed: int = 42
) -> list[tuple[str, str, str]]:
    rng = random.Random(seed)
    return rng.sample(rows, n)


def evaluate(
    analyzer: Analyzer,
    sample: list[tuple[str, str, str]],
    *,
    verbose: bool = False,
) -> dict[str, float | int]:
    """Run the analyzer over a sample and report match rates.

    Lemma match: case-insensitive equality of our lemma vs gold.
    Tag match: full string equality.
    Tag-prefix match: agreement on POS char only (our analysis category).
    """
    n = len(sample)
    lemma_hits = 0
    tag_hits = 0
    pos_hits = 0
    no_analysis = 0
    failures: list[
        tuple[str, str, str, str, str]
    ] = []  # (word, gold_tag, gold_lemma, our_tag, our_lemma)

    t0 = time.perf_counter()
    for word, gold_tag, gold_lemma in sample:
        result = analyzer.analyze(word)
        if not result.wordforms:
            no_analysis += 1
            failures.append((word, gold_tag, gold_lemma, "-", "-"))
            continue
        wf = result.wordforms[0]
        our_tag = to_tag(wf)
        # Pamatforma overrides the lexeme's lemma when set — prefix-stripped
        # readings (uzlaist via laist + uz-) stash the prefixed form there.
        our_lemma = wf.get("Pamatforma") or (wf.lexeme.lemma if wf.lexeme else "-")
        # Java preserves original capitalization for proper nouns even when
        # the lexicon stores the lemma lowercase.
        is_proper = wf.is_matching_strong("Lietvārda tips", "Īpašvārds")
        if is_proper and word and word[0].isupper():
            our_lemma = our_lemma[:1].upper() + our_lemma[1:]

        if our_lemma.casefold() == gold_lemma.casefold():
            lemma_hits += 1
        if our_tag == gold_tag:
            tag_hits += 1
        if our_tag and gold_tag and our_tag[0] == gold_tag[0]:
            pos_hits += 1
        if our_tag != gold_tag or our_lemma.casefold() != gold_lemma.casefold():
            failures.append((word, gold_tag, gold_lemma, our_tag, our_lemma))

    elapsed = time.perf_counter() - t0

    if verbose:
        print(f"\n=== {n} words analyzed in {elapsed:.1f}s ({n / elapsed:.0f} w/s) ===")
        print(f"Lemma matches: {lemma_hits}/{n} ({100 * lemma_hits / n:.1f}%)")
        print(f"Tag matches:   {tag_hits}/{n} ({100 * tag_hits / n:.1f}%)")
        print(f"POS matches:   {pos_hits}/{n} ({100 * pos_hits / n:.1f}%)")
        print(f"No analysis:   {no_analysis}/{n} ({100 * no_analysis / n:.1f}%)")

        # Bucket failures by category
        by_first_char = Counter()
        for w, gt, gl, ot, ol in failures:
            by_first_char[(gt[:1], ot[:1] if ot else "-")] += 1
        print("\nTop 10 failure POS-bucket pairs (gold→ours):")
        for (g, o), c in by_first_char.most_common(10):
            print(f"  {g!r} → {o!r}: {c}")

        print("\nSample failures (first 20):")
        for w, gt, gl, ot, ol in failures[:20]:
            print(f"  {w:18} gold={gt:15} {gl:15} | ours={ot:15} {ol}")

    return {
        "n": n,
        "lemma_hits": lemma_hits,
        "tag_hits": tag_hits,
        "pos_hits": pos_hits,
        "no_analysis": no_analysis,
        "lemma_pct": 100 * lemma_hits / n,
        "tag_pct": 100 * tag_hits / n,
        "pos_pct": 100 * pos_hits / n,
        "elapsed": elapsed,
    }


def test_parity_quick() -> None:
    """Smoke test for `pytest`: 100 random words, demand reasonable defaults."""
    rows = load_corpus()
    sample = sample_words(rows, 100)
    a = Analyzer()
    a.enable_guessing = True
    metrics = evaluate(a, sample)
    assert metrics["lemma_pct"] >= 60, f"Lemma parity regressed: {metrics}"


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    rows = load_corpus()
    print(f"Corpus: {len(rows):,} tokens loaded")
    sample = sample_words(rows, n)
    a = Analyzer()
    a.enable_guessing = True
    evaluate(a, sample, verbose=True)
