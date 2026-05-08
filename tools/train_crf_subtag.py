"""Train a sub-tag CRF (first 5 chars) — second level of hierarchical
disambiguation. Captures POS + the most-discriminative feature positions
(noun: type+gender+number+case; verb: type+reflexivity+mood).

Output: `tezaurs/data/crf_subtag.crfsuite`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sklearn_crfsuite

from tools.train_crf_tagger import load_sentences, sentence_features


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = REPO_ROOT / "reference" / "src" / "main" / "resources" / "train.txt"
DEFAULT_MODEL = REPO_ROOT / "tezaurs" / "data" / "crf_subtag.crfsuite"


def train(prefix_len: int = 5, corpus: Path = DEFAULT_CORPUS, out: Path = DEFAULT_MODEL) -> None:
    print(f"Loading {corpus}")
    sentences = list(load_sentences(corpus))
    print(f"  {len(sentences):,} sentences")

    print(f"Features (truncating tags to first {prefix_len} chars)...")
    t0 = time.perf_counter()
    X = [sentence_features(s) for s in sentences]
    y = [
        [(tag[:prefix_len] if tag else "-") for _, tag, _ in s]
        for s in sentences
    ]
    unique_labels = {label for seq in y for label in seq}
    print(f"  done in {time.perf_counter() - t0:.1f}s, unique labels: {len(unique_labels)}")

    print("Training L-BFGS CRF...")
    t0 = time.perf_counter()
    crf = sklearn_crfsuite.CRF(
        algorithm="lbfgs",
        c1=0.2,
        c2=0.2,
        max_iterations=30,
        all_possible_transitions=False,
        min_freq=2,
        model_filename=str(out),
        verbose=False,
    )
    crf.fit(X, y)
    print(f"  trained in {time.perf_counter() - t0:.0f}s")
    print(f"  model: {out} ({out.stat().st_size / 1_000_000:.2f} MB)")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    train(prefix_len=n)
