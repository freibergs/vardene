"""Paradigm and Ending — Python port of `lexicon/Paradigm.java`, `lexicon/Ending.java`, `lexicon/StemType.java`.

Loaded from `data/paradigms.json` (which already contains both Latvian and
Latgalian paradigms in a unified schema with a `language` field).

`Ending` inherits its grammatical attributes from its parent `Paradigm` —
e.g. a paradigm-level `Vārdšķira="Lietvārds"` applies to every ending in that
paradigm. The Java implementation mutates each ending; we expose a derived
view via `Ending.attributes` so the parent paradigm can be queried for the
inherited fields without copying state.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from importlib.resources import files
from pathlib import Path
from typing import ClassVar

from vardene.attributes import AttributeValues


class StemType(Enum):
    """Which stem (1=base, 2=present, 3=past) an ending attaches to."""

    BASE = 1
    PRESENT = 2
    PAST = 3

    @property
    def description_lv(self) -> str:
        return {1: "Pamatformas celms", 2: "Tagadnes celms", 3: "Pagātnes celms"}[self.value]

    @property
    def description_en(self) -> str:
        return {1: "Base stem", 2: "Present stem", 3: "Past stem"}[self.value]

    @classmethod
    def from_id(cls, raw: int | str) -> StemType:
        return cls(int(raw))


@dataclass(slots=True)
class Ending:
    """A single inflected ending within a paradigm.

    `mija` (stem alternation ID) is an index into the Mijas rule table —
    the actual transformation logic lives in `vardene.mijas` (phase 4).
    """

    id: int
    ending: str
    mija: int  # stem-change ID (0 = no alternation)
    stem_type: StemType
    lemma_ending_id: (
        int | None
    )  # which ending in this paradigm is the lemma form, if not the paradigm default
    do_not_generate: bool
    language_normalization: str | None
    own_attributes: AttributeValues  # attributes specific to this ending (combined with paradigm's at lookup time)
    paradigm: Paradigm | None = field(default=None, repr=False, compare=False)

    @property
    def attributes(self) -> AttributeValues:
        """Effective attributes: paradigm-level merged with this ending's own."""
        merged = (
            AttributeValues(self.paradigm.own_attributes) if self.paradigm else AttributeValues()
        )
        merged.add_all(self.own_attributes)
        return merged

    def stem(self, word: str) -> str:
        """Strip this ending from `word`. Raises if the word doesn't end with it."""
        if not word.endswith(self.ending):
            raise WrongEndingError(f"word {word!r} does not end with ending {self.ending!r}")
        return word[: len(word) - len(self.ending)] if self.ending else word

    def lemma_ending(self) -> Ending | None:
        """The ending in this paradigm that produces the lemma. Defaults to paradigm-level."""
        if self.lemma_ending_id is not None and self.paradigm is not None:
            return self.paradigm.ending_by_id(self.lemma_ending_id)
        return self.paradigm.lemma_ending() if self.paradigm else None

    def is_matching_strong(self, attribute: str, value: str) -> bool:
        return self.attributes.is_matching_strong(attribute, value)


class WrongEndingError(ValueError):
    """Raised by `Ending.stem` when the surface form doesn't end with the ending."""


@dataclass(slots=True)
class Paradigm:
    id: int
    name: str | None
    language: str
    stems: int  # 1, 2, or 3
    lemma_ending_id: int
    description: str | None
    description_en: str | None
    allowed_guess_endings: str | None
    own_attributes: AttributeValues
    endings: tuple[Ending, ...]

    def __post_init__(self) -> None:
        for e in self.endings:
            e.paradigm = self

    def ending_by_id(self, ending_id: int) -> Ending | None:
        for e in self.endings:
            if e.id == ending_id:
                return e
        return None

    def lemma_ending(self) -> Ending | None:
        return self.ending_by_id(self.lemma_ending_id)

    def endings_by_attribute(self, attribute: str, value: str) -> list[Ending]:
        return [e for e in self.endings if e.is_matching_strong(attribute, value)]

    def endings_by_attributes(self, av: AttributeValues) -> list[Ending]:
        return [e for e in self.endings if e.attributes.is_matching_strong_one_side(av)]

    @property
    def num_endings(self) -> int:
        return len(self.endings)


@dataclass(frozen=True, slots=True)
class LanguagePrefixes:
    language: str
    negation: tuple[str, ...]
    debitive: tuple[str, ...]
    superlative: tuple[str, ...]
    verb: tuple[str, ...]


class ParadigmCatalog:
    """All paradigms (Latvian + Latgalian) plus the global prefix lists.

    Singleton-ish: load lazily from `data/paradigms.json`. Look up by either
    `(language, id)` or globally-unique `name`.
    """

    _DEFAULT_FILENAME: ClassVar[str] = "paradigms.json"
    _instance: ClassVar[ParadigmCatalog | None] = None

    __slots__ = ("_by_lang_id", "_by_name", "core_files", "paradigms", "prefixes")

    def __init__(
        self,
        paradigms: tuple[Paradigm, ...],
        prefixes: tuple[LanguagePrefixes, ...],
        core_files: tuple[str, ...],
    ) -> None:
        self.paradigms = paradigms
        self.prefixes = prefixes
        self.core_files = core_files
        self._by_lang_id: dict[tuple[str, int], Paradigm] = {
            (p.language, p.id): p for p in paradigms
        }
        self._by_name: dict[str, Paradigm] = {p.name: p for p in paradigms if p.name is not None}

    @classmethod
    def load(cls, json_path: Path | None = None) -> ParadigmCatalog:
        path = json_path if json_path is not None else cls._default_data_path()
        with Path(path).open(encoding="utf-8") as f:
            data = json.load(f)

        paradigms = tuple(_paradigm_from_json(p) for p in data["paradigms"])
        prefixes = tuple(
            LanguagePrefixes(
                language=p["language"],
                negation=tuple(p["negation"]),
                debitive=tuple(p["debitive"]),
                superlative=tuple(p["superlative"]),
                verb=tuple(p["verb"]),
            )
            for p in data["prefixes"]
        )
        core_files = tuple(data["core_files"])
        return cls(paradigms, prefixes, core_files)

    @classmethod
    def instance(cls) -> ParadigmCatalog:
        if cls._instance is None:
            cls._instance = cls.load()
        return cls._instance

    @classmethod
    def _default_data_path(cls) -> Path:
        return Path(str(files("vardene").joinpath("data", cls._DEFAULT_FILENAME)))

    # --- lookups --------------------------------------------------------

    def by_id(self, paradigm_id: int, language: str = "lv") -> Paradigm | None:
        return self._by_lang_id.get((language, paradigm_id))

    def by_name(self, name: str) -> Paradigm | None:
        return self._by_name.get(name)

    def for_language(self, language: str) -> tuple[Paradigm, ...]:
        return tuple(p for p in self.paradigms if p.language == language)

    def prefixes_for(self, language: str) -> LanguagePrefixes | None:
        for p in self.prefixes:
            if p.language == language:
                return p
        return None


def _ending_from_json(d: Mapping[str, object]) -> Ending:
    own = AttributeValues(d["attributes"] or {})  # type: ignore[arg-type]
    le = d.get("lemma_ending_id")
    return Ending(
        id=int(d["id"]),  # type: ignore[arg-type]
        ending=str(d["ending"]),
        mija=int(d["stem_change"]),  # type: ignore[arg-type]
        stem_type=StemType.from_id(int(d["stem_id"])),  # type: ignore[arg-type]
        lemma_ending_id=int(le) if le is not None else None,  # type: ignore[arg-type]
        do_not_generate=bool(d["do_not_generate"]),
        language_normalization=str(d["language_normalization"])
        if d["language_normalization"] is not None
        else None,
        own_attributes=own,
    )


def _paradigm_from_json(d: Mapping[str, object]) -> Paradigm:
    own = AttributeValues(d["attributes"] or {})  # type: ignore[arg-type]
    endings = tuple(_ending_from_json(e) for e in d["endings"])  # type: ignore[arg-type]
    return Paradigm(
        id=int(d["id"]),  # type: ignore[arg-type]
        name=str(d["name"]) if d["name"] is not None else None,
        language=str(d["language"]),
        stems=int(d["stems"]),  # type: ignore[arg-type]
        lemma_ending_id=int(d["lemma_ending_id"]),  # type: ignore[arg-type]
        description=str(d["description"]) if d["description"] is not None else None,
        description_en=str(d["description_en"]) if d["description_en"] is not None else None,
        allowed_guess_endings=str(d["allowed_guess_endings"])
        if d["allowed_guess_endings"] is not None
        else None,
        own_attributes=own,
        endings=endings,
    )
