"""Corpus frequency statistics — used to rank Wordform candidates.

The Java pipeline does conditional-random-field disambiguation
(`MorphoEvaluate`/`Statistics.java`); this MVP uses a simpler product-of-
frequencies score: `score(wordform) = (lexeme_freq + 1) * (ending_freq + 1)`.

Empirically this picks the right reading for the common homograph cases
(`raksta` → verb `rakstīt`, `pieņēmis` → verb participle `pieņemt`, etc.)
without the full CRF machinery.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import ClassVar

from tezaurs.wordform import Wordform


class Statistics:
    """Loads `data/statistics.json` once. Provides `score(wordform)` and
    `disambiguate(wordforms)` to sort candidates by likelihood."""

    _DEFAULT_FILENAME: ClassVar[str] = "statistics.json"
    _instance: ClassVar[Statistics | None] = None

    __slots__ = ("ending_freq", "lexeme_freq")

    def __init__(self, ending_freq: dict[int, int], lexeme_freq: dict[int, int]) -> None:
        self.ending_freq: dict[int, int] = ending_freq
        self.lexeme_freq: dict[int, int] = lexeme_freq

    @classmethod
    def load(cls, json_path: Path | None = None) -> Statistics:
        path = json_path if json_path is not None else cls._default_data_path()
        with Path(path).open(encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            ending_freq={int(k): v for k, v in data["ending_frequencies"].items()},
            lexeme_freq={int(k): v for k, v in data["lexeme_frequencies"].items()},
        )

    @classmethod
    def instance(cls) -> Statistics:
        if cls._instance is None:
            cls._instance = cls.load()
        return cls._instance

    @classmethod
    def _default_data_path(cls) -> Path:
        return Path(str(files("tezaurs").joinpath("data", cls._DEFAULT_FILENAME)))

    # Java `corpus/Statistics.java` line 50: lexemes weighted 1000× endings.
    # We mirror this constant exactly for 1:1 parity with the upstream's
    # `getEstimate()` formula.
    LEXEME_WEIGHT = 1000.0

    def estimate(self, wf: Wordform) -> float:
        """1:1 port of Java `Statistics.getEstimate(AttributeValues)`:

            estimate = 0.1 + ending_freq + lexeme_freq * 1000

        That's it — additive linear model, no multiplicative smoothing,
        no POS biases, no case biases. The upstream tagger uses this single
        scalar for `getBestWordform`; sentence-level CRF disambiguation
        happens in a separate service (the morphotagger endpoint).
        """
        estimate = 0.1
        if wf.ending is not None:
            estimate += self.ending_freq.get(wf.ending.id, 0)
        if wf.lexeme is not None and wf.lexeme.lexeme_id is not None:
            estimate += self.lexeme_freq.get(wf.lexeme.lexeme_id, 0) * self.LEXEME_WEIGHT
        return estimate

    def score(self, wf: Wordform, *, prefer_proper: bool = False) -> tuple[float, int]:
        """Score a wordform for disambiguation. Higher tuple = more likely.

        Primary key = Java-equivalent `estimate()`. The capitalization tiebreaker
        is a small bias used only when the corpus signal alone is silent —
        capitalized input tokens nudge toward Īpašvārds readings, lowercase
        toward Sugas vārds. This matches what Java's analyzer effectively does
        through `properName` flag propagation.
        """
        primary = self.estimate(wf)
        if wf.lexeme is None:
            return (primary - 5.0, 0)  # Java penalizes guesses by -5 (Word.java:274)
        is_proper = wf.is_matching_strong("Lietvārda tips", "Īpašvārds")
        proper_pref = 1 if (prefer_proper == is_proper) else 0
        return (primary, proper_pref)

    def disambiguate(
        self, wordforms: list[Wordform], *, prefer_proper: bool = False
    ) -> list[Wordform]:
        """Return wordforms sorted by descending score (Java `getBestWordform` semantics)."""
        return sorted(
            wordforms, key=lambda wf: self.score(wf, prefer_proper=prefer_proper), reverse=True
        )

