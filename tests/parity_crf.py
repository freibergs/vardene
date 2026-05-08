"""Sentence-aware parity test using the CRF tagger.

Unlike `parity.py` which analyzes word-by-word, this evaluates sentence-level
disambiguation — the CRF picks each token's tag with full context.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.train_crf_tagger import load_sentences
from vardene.analyzer import Analyzer
from vardene.markup import to_tag

CORPUS = Path(__file__).resolve().parent.parent / "tools" / "data" / "train.txt"


def evaluate(num_sentences: int = 200, seed: int = 42) -> dict[str, float | int]:
    sentences = list(load_sentences(CORPUS))
    rng = random.Random(seed)
    sample = rng.sample(sentences, num_sentences)

    a = Analyzer()
    a.enable_guessing = True

    t0 = time.perf_counter()
    n = 0
    lemma_hits = 0
    tag_hits = 0
    pos_hits = 0
    for sent in sample:
        words = [w for w, _, _ in sent]
        results = a.analyze_sentence(words)
        for (word, gold_tag, gold_lemma), result in zip(sent, results, strict=True):
            n += 1
            if not result.wordforms:
                continue
            wf = result.wordforms[0]
            our_tag = to_tag(wf)
            our_lemma = wf.get("Pamatforma") or (wf.lexeme.lemma if wf.lexeme else "-")
            if our_lemma.casefold() == gold_lemma.casefold():
                lemma_hits += 1
            if our_tag == gold_tag:
                tag_hits += 1
            if our_tag and gold_tag and our_tag[0] == gold_tag[0]:
                pos_hits += 1
    elapsed = time.perf_counter() - t0

    print(f"\n=== {num_sentences} sentences ({n} tokens) in {elapsed:.1f}s ===")
    print(f"Lemma matches: {lemma_hits}/{n} ({100 * lemma_hits / n:.1f}%)")
    print(f"Tag matches:   {tag_hits}/{n} ({100 * tag_hits / n:.1f}%)")
    print(f"POS matches:   {pos_hits}/{n} ({100 * pos_hits / n:.1f}%)")
    return {
        "n": n,
        "lemma_pct": 100 * lemma_hits / n,
        "tag_pct": 100 * tag_hits / n,
        "pos_pct": 100 * pos_hits / n,
        "elapsed": elapsed,
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    evaluate(n)
