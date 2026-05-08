"""Per-POS multinomial logistic regression classifier — second-level disambiguator.

For each POS char (n/v/a/p/r/...), train a sklearn LogisticRegression that maps
per-token feature vectors to the FULL tag string. Much faster than CRF since:
  - Per-token, not per-sequence (no Viterbi, no forward-backward)
  - Only uses in-POS tokens for training (way smaller dataset per model)
  - sklearn's lbfgs solver is very fast for multinomial LR

Output: `tezaurs/data/per_pos_clf.pkl` containing dict[pos_char, (vectorizer, clf)].
"""

from __future__ import annotations

import pickle
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from tools.train_crf_tagger import load_sentences, sentence_features


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = REPO_ROOT / "tools" / "data" / "train.txt"
DEFAULT_OUT = REPO_ROOT / "tezaurs" / "data" / "per_pos_clf.pkl"


# POS chars worth training (skip ones with too few tokens or a single tag).
TRAIN_POS = set("nvaprscm")


def train_all() -> None:
    print(f"Loading {DEFAULT_CORPUS}")
    sentences = list(load_sentences(DEFAULT_CORPUS))
    print(f"  {len(sentences):,} sentences")

    print("Extracting features...")
    t0 = time.perf_counter()
    # Flatten to (features_dict, gold_tag) pairs grouped by POS.
    by_pos: dict[str, list[tuple[dict, str]]] = defaultdict(list)
    for sent in sentences:
        feats = sentence_features(sent)
        for (_, tag, _), feat in zip(sent, feats, strict=True):
            if not tag or len(tag) < 1:
                continue
            pos = tag[0]
            if pos in TRAIN_POS:
                by_pos[pos].append((feat, tag))
    print(f"  done in {time.perf_counter() - t0:.1f}s")

    models: dict[str, tuple[DictVectorizer, LogisticRegression]] = {}
    for pos in sorted(by_pos.keys()):
        items = by_pos[pos]
        if len(items) < 200:
            print(f"  {pos!r}: {len(items)} tokens — skipping (too few)")
            continue
        print(f"\n=== POS {pos!r}: {len(items):,} tokens ===")
        # Drop labels seen <2 times (regularization noise)
        tag_counts: Counter[str] = Counter(tag for _, tag in items)
        kept = [(f, t) for f, t in items if tag_counts[t] >= 2]
        feats = [f for f, _ in kept]
        labels = [t for _, t in kept]
        unique_tags = sorted(set(labels))
        print(f"  {len(unique_tags)} unique tags after filtering, {len(kept):,} samples")

        t0 = time.perf_counter()
        vec = DictVectorizer(sparse=True)
        X = vec.fit_transform(feats)
        # `saga` is much faster than lbfgs for sparse multinomial logistic regression
        # at this scale; supports L2 + parallel gradient computation.
        clf = LogisticRegression(
            max_iter=100,
            solver="saga",
            C=1.0,
            n_jobs=-1,
            verbose=0,
            tol=1e-3,
        )
        clf.fit(X, labels)
        print(f"  trained in {time.perf_counter() - t0:.0f}s; {X.shape[1]:,} features")
        models[pos] = (vec, clf)
        # Save incrementally so partial progress isn't lost on interrupt.
        DEFAULT_OUT.parent.mkdir(parents=True, exist_ok=True)
        with DEFAULT_OUT.open("wb") as f:
            pickle.dump(models, f)

    DEFAULT_OUT.parent.mkdir(parents=True, exist_ok=True)
    with DEFAULT_OUT.open("wb") as f:
        pickle.dump(models, f)
    print(f"\nSaved {len(models)} per-POS classifiers to {DEFAULT_OUT}")
    print(f"  size: {DEFAULT_OUT.stat().st_size / 1_000_000:.1f} MB")


if __name__ == "__main__":
    train_all()
