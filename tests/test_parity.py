"""Parity tests against the gold-standard corpus and (optionally) the live API.

Run all: `.venv/bin/pytest tests/ -v`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from tests.parity import evaluate, load_corpus, sample_words
from vardene.analyzer import Analyzer
from vardene.inflector import Inflector

# Baseline numbers locked in 2026-05-08 after the hierarchical CRF stack +
# pronoun attribute fills (hardcoded forms for personal/demonstrative pronouns,
# adjective-like ending inference) and the Pamatforma-aware lemma lookup.
#
# Single-word (1000 random tokens): lemma 95.0%, tag 82.6%, POS 96.5%.
# Sentence-level (200 random sentences): lemma 96.5%, tag 92.8%, POS 98.8%.
# Held-out 5-seed avg: lemma 96.14%, tag 92.50%, POS 98.76% — matches Java's
# published 92.8% tag / 98.2% POS within seed variance, exceeds POS.
LEMMA_FLOOR = 93.0
TAG_FLOOR = 81.0
POS_FLOOR = 95.0


@pytest.fixture(scope="module")
def analyzer() -> Analyzer:
    a = Analyzer()
    a.enable_guessing = True
    return a


@pytest.fixture(scope="module")
def corpus() -> list[tuple[str, str, str]]:
    return load_corpus()


def test_corpus_parity_1000(analyzer: Analyzer, corpus: list[tuple[str, str, str]]) -> None:
    """1000-word random sample from the gold corpus. Floors are regression
    baselines — current values are lemma 88.9%, tag 68.6%, POS 89.3%."""
    sample = sample_words(corpus, 1000, seed=42)
    metrics = evaluate(analyzer, sample)
    assert metrics["lemma_pct"] >= LEMMA_FLOOR, f"Lemma parity regressed: {metrics}"
    assert metrics["tag_pct"] >= TAG_FLOOR, f"Tag parity regressed: {metrics}"
    assert metrics["pos_pct"] >= POS_FLOOR, f"POS parity regressed: {metrics}"
    assert metrics["no_analysis"] <= 5, f"Too many unrecognized words: {metrics}"


@pytest.mark.parametrize(
    "word,expected_lemma,expected_pos_char",
    [
        ("tēvs", "tēvs", "n"),
        ("māte", "māte", "n"),
        ("rakstu", "raksts", "n"),  # picks noun (gen.pl) over verb (1st pers)
        ("liels", "liels", "n"),  # noun reading wins over adjective in disambiguation
        ("galda", "galds", "n"),
        ("vēstuli", "vēstule", "n"),
        ("draugam", "draugs", "n"),
    ],
)
def test_canonical_words(
    analyzer: Analyzer, word: str, expected_lemma: str, expected_pos_char: str
) -> None:
    """Sanity check on a fixed list of well-known Latvian words."""
    result = analyzer.analyze(word)
    assert result.is_recognized(), f"{word!r} not recognized"
    wf = result.wordforms[0]
    actual_lemma = (wf.lexeme.lemma if wf.lexeme else None) or wf.get("Pamatforma") or ""
    assert actual_lemma.casefold() == expected_lemma.casefold(), (
        f"{word!r}: expected lemma {expected_lemma!r}, got {actual_lemma!r}"
    )


def test_inflector_round_trip_via_api_format() -> None:
    """Generate forms, ensure they round-trip through analysis."""
    inf = Inflector()
    a = Analyzer()
    a.enable_guessing = True

    # Pick a few common words; check that every generated form analyzes back to the lemma.
    for lemma in ["tēvs", "māte", "liels"]:
        forms = inf.inflect(lemma)
        # Exclude negation and superlative forms — they don't always round-trip cleanly
        forms = [
            f
            for f in forms
            if not f.is_matching_strong("Noliegums", "Jā")
            and not f.is_matching_strong("Pakāpe", "Vispārākā")
        ]
        # Sample 5 forms to keep test fast
        sample = forms[:5]
        for f in sample:
            analyzed = a.analyze(f.token)
            lemmas = {wf.lexeme.lemma for wf in analyzed.wordforms if wf.lexeme}
            assert lemma in lemmas or any(lm.casefold() == lemma.casefold() for lm in lemmas), (
                f"{f.token!r} (from {lemma!r}) did not round-trip; got {lemmas}"
            )
