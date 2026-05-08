"""Train a POS-only CRF on `train.txt` — first level of hierarchical
disambiguation. Predicts only the part-of-speech char (13 classes), which is
fast (~30s) and resolves the biggest disambiguation gap (noun/verb confusion).

Output: `tezaurs/data/crf_pos.crfsuite`.
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
DEFAULT_MODEL = REPO_ROOT / "tezaurs" / "data" / "crf_pos.crfsuite"


def train(corpus: Path = DEFAULT_CORPUS, out: Path = DEFAULT_MODEL) -> None:
    print(f"Loading {corpus}")
    sentences = list(load_sentences(corpus))
    print(f"  {len(sentences):,} sentences")

    print("Features...")
    t0 = time.perf_counter()
    X = [sentence_features(s) for s in sentences]
    # Reduce labels to POS char only (13 classes)
    y = [[(tag[:1] if tag else "-") for _, tag, _ in s] for s in sentences]
    print(f"  done in {time.perf_counter() - t0:.1f}s")

    unique_labels = {label for seq in y for label in seq}
    print(f"  unique POS labels: {sorted(unique_labels)}")

    print("Training L-BFGS CRF on POS labels (13 classes)...")
    t0 = time.perf_counter()
    crf = sklearn_crfsuite.CRF(
        algorithm="lbfgs",
        c1=0.1,
        c2=0.1,
        max_iterations=50,
        all_possible_transitions=True,
        min_freq=2,
        model_filename=str(out),
        verbose=False,
    )
    crf.fit(X, y)
    print(f"  trained in {time.perf_counter() - t0:.0f}s")
    print(f"  model: {out} ({out.stat().st_size / 1_000_000:.2f} MB)")


if __name__ == "__main__":
    train()
