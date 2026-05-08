"""Lexeme + Lexicon — Python port of `lexicon/Lexeme.java` and `lexicon/Lexicon.java`.

Backed by `data/lexemes.parquet` (~411k rows, ~5 MB on disk). The Parquet table
is kept in columnar form and only converted to `Lexeme` objects on demand.

Lookup indexes (lemma, lexeme_id, paradigm_name) are built lazily on first use
so cold-start cost stays minimal when consumers only need columnar access.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import ClassVar

import pyarrow as pa
import pyarrow.parquet as pq

from tezaurs.attributes import AttributeValues
from tezaurs.paradigm import Ending, Paradigm, ParadigmCatalog, StemType


@dataclass(slots=True)
class Lexeme:
    """A lexicon entry: stems + identifying metadata + per-lexeme attribute overrides.

    The effective attribute set merges paradigm-level attributes with the
    lexeme's own (`merged_attributes`).
    """

    lexeme_id: int | None
    entry_id: int | None
    human_id: str | None
    lemma: str | None
    stems: dict[StemType, str]  # populated for XML-source lexemes; empty for JSONL-only rows
    paradigm: Paradigm | None
    own_attributes: AttributeValues
    source: str
    language: str

    def stem(self, stem_type: StemType = StemType.BASE) -> str | None:
        return self.stems.get(stem_type)

    @property
    def merged_attributes(self) -> AttributeValues:
        merged = AttributeValues(self.paradigm.own_attributes) if self.paradigm else AttributeValues()
        merged.add_all(self.own_attributes)
        return merged

    def endings(self) -> tuple[Ending, ...]:
        return self.paradigm.endings if self.paradigm else ()


class Lexicon:
    """All lexemes, indexable by lemma, ID, and paradigm name.

    Internally stores the lexeme columns as a `pyarrow.Table` and constructs
    `Lexeme` objects lazily on access.
    """

    _DEFAULT_FILENAME: ClassVar[str] = "lexemes.parquet"
    _instance: ClassVar[Lexicon | None] = None

    __slots__ = (
        "paradigms",
        "_table",
        "_by_lexeme_id",
        "_by_lemma",
        "_by_paradigm_name",
    )

    def __init__(self, paradigms: ParadigmCatalog, table: pa.Table) -> None:
        self.paradigms = paradigms
        self._table = table
        self._by_lexeme_id: dict[int, int] | None = None
        self._by_lemma: dict[str, list[int]] | None = None
        self._by_paradigm_name: dict[str, list[int]] | None = None

    @classmethod
    def load(
        cls,
        parquet_path: Path | None = None,
        paradigms: ParadigmCatalog | None = None,
    ) -> Lexicon:
        path = parquet_path if parquet_path is not None else cls._default_data_path()
        table = pq.read_table(path)
        return cls(paradigms or ParadigmCatalog.instance(), table)

    @classmethod
    def instance(cls) -> Lexicon:
        if cls._instance is None:
            cls._instance = cls.load()
        return cls._instance

    @classmethod
    def _default_data_path(cls) -> Path:
        return Path(str(files("tezaurs").joinpath("data", cls._DEFAULT_FILENAME)))

    # --- columnar accessors --------------------------------------------

    def __len__(self) -> int:
        return self._table.num_rows

    @property
    def table(self) -> pa.Table:
        """Raw columnar view, for filtered scans without materializing Lexeme objects."""
        return self._table

    # --- lookups (lazy index build) ------------------------------------

    def lexeme_by_id(self, lexeme_id: int) -> Lexeme | None:
        if self._by_lexeme_id is None:
            self._build_id_index()
        idx = self._by_lexeme_id.get(lexeme_id)
        return self._row_to_lexeme(idx) if idx is not None else None

    def lexemes_by_lemma(self, lemma: str) -> list[Lexeme]:
        if self._by_lemma is None:
            self._build_lemma_index()
        return [self._row_to_lexeme(i) for i in self._by_lemma.get(lemma, ())]

    def lexemes_by_paradigm(self, paradigm_name: str) -> list[Lexeme]:
        if self._by_paradigm_name is None:
            self._build_paradigm_index()
        return [self._row_to_lexeme(i) for i in self._by_paradigm_name.get(paradigm_name, ())]

    # --- index builders -------------------------------------------------

    def _build_id_index(self) -> None:
        ids = self._table.column("lexeme_id").to_pylist()
        index: dict[int, int] = {}
        for row, lex_id in enumerate(ids):
            if lex_id is not None and lex_id not in index:
                index[lex_id] = row
        self._by_lexeme_id = index

    def _build_lemma_index(self) -> None:
        lemmas = self._table.column("lemma").to_pylist()
        index: dict[str, list[int]] = {}
        for row, lemma in enumerate(lemmas):
            if lemma is not None:
                index.setdefault(lemma, []).append(row)
        self._by_lemma = index

    def _build_paradigm_index(self) -> None:
        names = self._table.column("paradigm_name").to_pylist()
        index: dict[str, list[int]] = {}
        for row, name in enumerate(names):
            if name is not None:
                index.setdefault(name, []).append(row)
        self._by_paradigm_name = index

    # --- row materialization -------------------------------------------

    def _row_to_lexeme(self, row: int) -> Lexeme:
        t = self._table
        attrs_json = t.column("attributes_json")[row].as_py()
        own = AttributeValues(json.loads(attrs_json) if attrs_json else {})

        stems: dict[StemType, str] = {}
        for st, col in ((StemType.BASE, "stem1"), (StemType.PRESENT, "stem2"), (StemType.PAST, "stem3")):
            v = t.column(col)[row].as_py()
            if v is not None:
                stems[st] = v

        paradigm_name = t.column("paradigm_name")[row].as_py()
        paradigm = self.paradigms.by_name(paradigm_name) if paradigm_name else None

        return Lexeme(
            lexeme_id=t.column("lexeme_id")[row].as_py(),
            entry_id=t.column("entry_id")[row].as_py(),
            human_id=t.column("human_id")[row].as_py(),
            lemma=t.column("lemma")[row].as_py(),
            stems=stems,
            paradigm=paradigm,
            own_attributes=own,
            source=t.column("source")[row].as_py(),
            language=t.column("language")[row].as_py(),
        )
