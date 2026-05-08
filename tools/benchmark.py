"""Reproducibility benchmark for the Python port (paper Table 2).

Usage:
    python -m tools.benchmark              # full pipeline, 5-seed held-out
    python -m tools.benchmark --train      # report on full corpus
    python -m tools.benchmark --no-overrides --no-viterbi  # ablations
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.train_crf_tagger import load_sentences  # noqa: E402
from tezaurs.analyzer import Analyzer  # noqa: E402
from tezaurs.markup import to_tag  # noqa: E402

CORPUS = REPO_ROOT / "tools" / "data" / "train.txt"


def held_out(sentences, holdout_seed: int = 0xDEADBEEF, fraction: float = 0.2):
    rng = random.Random(holdout_seed)
    shuffled = sentences[:]
    rng.shuffle(shuffled)
    split = int(len(shuffled) * (1.0 - fraction))
    return shuffled[split:]


def evaluate_seed(analyzer: Analyzer, test_set, seed: int, n: int = 200):
    rng = random.Random(seed)
    sample = rng.sample(test_set, min(n, len(test_set)))
    total = lemma = tag = pos = 0
    t0 = time.perf_counter()
    for sent in sample:
        words = [s[0] for s in sent]
        results = analyzer.analyze_sentence(words)
        for (tok, gt, gl), result in zip(sent, results, strict=True):
            total += 1
            if not result.wordforms:
                continue
            wf = result.wordforms[0]
            our_tag = to_tag(wf)
            our_lemma = wf.get("Pamatforma") or (
                wf.lexeme.lemma if wf.lexeme else "-"
            )
            if our_lemma.casefold() == gl.casefold():
                lemma += 1
            if our_tag == gt:
                tag += 1
            if our_tag and gt and our_tag[0] == gt[0]:
                pos += 1
    elapsed = time.perf_counter() - t0
    return {
        "n": total,
        "lemma_pct": 100 * lemma / total,
        "tag_pct": 100 * tag / total,
        "pos_pct": 100 * pos / total,
        "tok_per_sec": total / elapsed,
        "elapsed_s": elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 7, 42, 100, 2024])
    parser.add_argument("--n", type=int, default=200, help="sentences per seed")
    parser.add_argument("--train", action="store_true",
                        help="evaluate on full corpus (not held-out)")
    parser.add_argument("--no-overrides", action="store_true",
                        help="disable per-form corpus overrides")
    parser.add_argument("--no-viterbi", action="store_true",
                        help="disable bigram-Viterbi rescoring")
    args = parser.parse_args()

    print(f"Loading corpus from {CORPUS}…")
    sentences = list(load_sentences(CORPUS))
    print(f"  {len(sentences)} sentences, {sum(len(s) for s in sentences)} tokens")

    if args.train:
        test = sentences
        print("Evaluating on full corpus (TRAIN — overfit signal)")
    else:
        test = held_out(sentences)
        print(f"Held-out 20%: {len(test)} sentences")

    analyzer = Analyzer()
    analyzer.enable_guessing = True

    if args.no_overrides:
        # Empty out the form-overrides table at runtime.
        from tezaurs import analyzer as _a
        _a._FORM_STRONG_OVERRIDES = {}
        _a._VERB_TRANSITIVITY = {}
        _a._VERB_TYPE = {}
        _a._ADVERB_PAKAPE = {}
        print("  Overrides DISABLED")
    if args.no_viterbi:
        from tezaurs import crf_tagger as _c
        # Hack: empty bigrams forces the per-token greedy rescore path.
        if analyzer._get_crf_tagger() is not None:
            tagger = _c.CRFTagger.instance()
            if tagger is not None:
                tagger._bigrams = {}
        print("  Viterbi DISABLED (per-token greedy)")

    # Warm up.
    analyzer.analyze("tēvs")

    print(f"\nseed   N      Lemma     Tag      POS     tok/s")
    print(f"------------------------------------------------")
    rows = []
    for seed in args.seeds:
        m = evaluate_seed(analyzer, test, seed, args.n)
        rows.append(m)
        print(f"{seed:5d} {m['n']:5d}  {m['lemma_pct']:6.2f}%  "
              f"{m['tag_pct']:6.2f}%  {m['pos_pct']:6.2f}%  {m['tok_per_sec']:6.0f}")

    if len(rows) > 1:
        n_seeds = len(rows)
        avg_l = sum(r["lemma_pct"] for r in rows) / n_seeds
        avg_t = sum(r["tag_pct"] for r in rows) / n_seeds
        avg_p = sum(r["pos_pct"] for r in rows) / n_seeds
        avg_s = sum(r["tok_per_sec"] for r in rows) / n_seeds
        print(f"------------------------------------------------")
        print(f"avg          {avg_l:6.2f}%  {avg_t:6.2f}%  {avg_p:6.2f}%  {avg_s:6.0f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
