"""Train a CRF morphological tagger on `train.txt` — Python equivalent of
LVTagger's Stanford CMM tagger. Outputs `tezaurs/data/crf_tagger.crfsuite`.

Features per token (lexical only — fast to extract, learns rich patterns):
  - word, lower(word), word shape (Stanford `dan2useLC`)
  - prefixes & suffixes (1-4 chars)
  - first-letter capitalization, all-caps, has-digit
  - previous/next word shape and lowercased form (Markov context)

Morphology candidates are NOT used as training features — they're consumed
at inference time by `crf_tagger.py` to filter the CRF's predictions to
only valid analyses. This decouples training (fast, lexical-only) from
inference (constrained to morphology engine output).

Run: `python -m tools.train_crf_tagger`  — ~30s on 200K sentences.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sklearn_crfsuite


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = REPO_ROOT / "tools" / "data" / "train.txt"
DEFAULT_MODEL = REPO_ROOT / "tezaurs" / "data" / "crf_tagger.crfsuite"


def load_sentences(path: Path) -> Iterator[list[tuple[str, str, str]]]:
    """Yield sentences as `[(word, gold_tag, gold_lemma), ...]`. Lines starting
    with `<` (sentence/glue markers) are treated as boundary signals."""
    sentence: list[tuple[str, str, str]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            if line == "<s>":
                sentence = []
                continue
            if line == "</s>":
                if sentence:
                    yield sentence
                sentence = []
                continue
            if line.startswith("<"):
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                sentence.append((parts[0], parts[1], parts[2]))


def word_shape(word: str) -> str:
    """Stanford `dan2useLC`-style: each char → 'X' (upper) / 'x' (lower) /
    '9' (digit) / '.' (other), with consecutive duplicates collapsed."""
    out: list[str] = []
    for c in word:
        if c.isupper():
            t = "X"
        elif c.islower():
            t = "x"
        elif c.isdigit():
            t = "9"
        else:
            t = "."
        if out and out[-1] == t:
            continue
        out.append(t)
    return "".join(out)


def token_features(words: list[str], i: int) -> dict[str, object]:
    word = words[i]
    lower = word.lower()
    feats: dict[str, object] = {
        "bias": 1.0,
        "word.lower": lower,
        "word.shape": word_shape(word),
        "word.isupper": word.isupper(),
        "word.istitle": word.istitle(),
        "word.isdigit": word.isdigit(),
        "word.hasdigit": any(c.isdigit() for c in word),
    }
    for n in range(1, 5):
        if len(word) >= n:
            feats[f"suffix-{n}"] = lower[-n:]
            feats[f"prefix-{n}"] = lower[:n]
    if i > 0:
        prev = words[i - 1]
        feats["prev.lower"] = prev.lower()
        feats["prev.shape"] = word_shape(prev)
    else:
        feats["BOS"] = True
    if i < len(words) - 1:
        nxt = words[i + 1]
        feats["next.lower"] = nxt.lower()
        feats["next.shape"] = word_shape(nxt)
    else:
        feats["EOS"] = True
    return feats


def sentence_features(sent: list[tuple[str, str, str]]) -> list[dict[str, object]]:
    words = [w for w, _, _ in sent]
    return [token_features(words, i) for i in range(len(words))]


def train_crf(
    corpus: Path = DEFAULT_CORPUS,
    out: Path = DEFAULT_MODEL,
    max_sentences: int | None = None,
) -> None:
    print(f"Loading sentences from {corpus} ...")
    sentences = list(load_sentences(corpus))
    if max_sentences is not None:
        sentences = sentences[:max_sentences]
    print(f"  {len(sentences):,} sentences, {sum(len(s) for s in sentences):,} tokens")

    print("Extracting features...")
    t0 = time.perf_counter()
    X = [sentence_features(s) for s in sentences]
    y = [[tag for _, tag, _ in s] for s in sentences]
    print(f"  done in {time.perf_counter() - t0:.1f}s")

    print("Training CRF (L-BFGS)...")
    t0 = time.perf_counter()
    # Averaged Perceptron — much faster than L-BFGS for the high-cardinality
    # output space of full Latvian morphological tags (1000+ classes). Quality
    # is comparable for sequence tagging on this corpus size.
    crf = sklearn_crfsuite.CRF(
        algorithm="ap",
        max_iterations=20,
        all_possible_transitions=False,
        min_freq=2,
        model_filename=str(out),
        verbose=True,
    )
    crf.fit(X, y)
    print(f"  trained in {time.perf_counter() - t0:.0f}s")
    print(f"  model: {out} ({out.stat().st_size / 1_000_000:.1f} MB)")


if __name__ == "__main__":
    max_n = int(sys.argv[1]) if len(sys.argv) > 1 else None
    train_crf(max_sentences=max_n)
