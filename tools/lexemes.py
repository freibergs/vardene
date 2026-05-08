"""Unified lexeme extractor — nine sources → one Parquet table.

Sources:
  - JSONL: tezaurs_lexemes.json (lv), tezaurs_latgalian.json (ltg)
  - XML:   Lexicon_minicore.xml, Lexicon_core.xml, Lexicon_firstnames.xml,
           Lexicon_vietas.xml, Lexicon_sv.xml, Lexicon_valerijs.xml,
           Lexicon_onomastica.xml, Latgalian_minicore.xml

XML lexicons nest <Lexeme> inside <Paradigm> blocks: the parent paradigm
provides the paradigm_id; the lexeme provides stems and attributes.

We stream the 32MB onomastica with lxml.iterparse and clear elements on the
fly to keep memory bounded.

Lemma synthesis: ~280 lexemes (in core/minicore) lack Pamatforma; for those we
compute lemma = stem1 + paradigm.endings[lemma_ending_id].ending.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

# Per-source language and label. Order = priority for de-duplication later.
XML_SOURCES: tuple[tuple[str, str, str], ...] = (
    # (filename, source_label, language)
    ("Lexicon_minicore.xml", "minicore", "lv"),
    ("Lexicon_core.xml", "core", "lv"),
    ("Lexicon_firstnames.xml", "firstnames", "lv"),
    ("Lexicon_vietas.xml", "vietas", "lv"),
    ("Lexicon_sv.xml", "sv", "lv"),
    ("Lexicon_valerijs.xml", "valerijs", "lv"),
    ("Lexicon_onomastica.xml", "onomastica", "lv"),
    ("Latgalian_minicore.xml", "minicore", "ltg"),
)

JSONL_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("tezaurs_lexemes.json", "vardene", "lv"),
    ("tezaurs_latgalian.json", "vardene", "ltg"),
)


@dataclass(slots=True)
class LemmaSynthesizer:
    """Builds the lemma string for XML lexemes without Pamatforma.

    Looks up the paradigm's lemma-ending (the surface ending that, attached to
    stem1, yields the dictionary form) from the canonical paradigms.json.

    Paradigm IDs are NOT globally unique across languages (lv id=1 and ltg id=1
    are different paradigms), so we key by (language, id).
    """

    lemma_ending_by_lang_id: dict[tuple[str, int], str]

    @classmethod
    def from_paradigms_json(cls, paradigms_json: Path) -> LemmaSynthesizer:
        with paradigms_json.open(encoding="utf-8") as f:
            data = json.load(f)
        mapping: dict[tuple[str, int], str] = {}
        for p in data["paradigms"]:
            target_id = p["lemma_ending_id"]
            for e in p["endings"]:
                if e["id"] == target_id:
                    mapping[(p["language"], p["id"])] = e["ending"]
                    break
        return cls(mapping)

    def synthesize(self, language: str, paradigm_id: int | None, stem1: str | None) -> str | None:
        if stem1 is None:
            return None
        ending = (
            self.lemma_ending_by_lang_id.get((language, paradigm_id))
            if paradigm_id is not None
            else None
        )
        return stem1 + ending if ending is not None else stem1


# Output column buffers (one list each — written as a single Parquet table at end).
class _Buffers:
    __slots__ = (
        "attributes_json",
        "entry_id",
        "human_id",
        "language",
        "lemma",
        "lexeme_id",
        "paradigm_id",
        "paradigm_name",
        "source",
        "stem1",
        "stem2",
        "stem3",
    )

    def __init__(self) -> None:
        self.lexeme_id: list[int | None] = []
        self.entry_id: list[int | None] = []
        self.human_id: list[str | None] = []
        self.paradigm_id: list[int | None] = []
        self.paradigm_name: list[str | None] = []
        self.lemma: list[str | None] = []
        self.stem1: list[str | None] = []
        self.stem2: list[str | None] = []
        self.stem3: list[str | None] = []
        self.attributes_json: list[str | None] = []
        self.source: list[str] = []
        self.language: list[str] = []

    def append(
        self,
        *,
        lexeme_id: int | None,
        entry_id: int | None,
        human_id: str | None,
        paradigm_id: int | None,
        paradigm_name: str | None,
        lemma: str | None,
        stem1: str | None,
        stem2: str | None,
        stem3: str | None,
        attributes_json: str | None,
        source: str,
        language: str,
    ) -> None:
        self.lexeme_id.append(lexeme_id)
        self.entry_id.append(entry_id)
        self.human_id.append(human_id)
        self.paradigm_id.append(paradigm_id)
        self.paradigm_name.append(paradigm_name)
        self.lemma.append(lemma)
        self.stem1.append(stem1)
        self.stem2.append(stem2)
        self.stem3.append(stem3)
        self.attributes_json.append(attributes_json)
        self.source.append(source)
        self.language.append(language)

    def __len__(self) -> int:
        return len(self.source)


def _norm_attrs(elem: etree._Element) -> dict[str, str]:
    """Read inner <Attributes ... /> as dict with `_` → ` ` key normalization."""
    child = elem.find("Attributes")
    if child is None:
        return {}
    return {k.replace("_", " "): v for k, v in child.attrib.items()}


def _attrs_to_json(attrs: dict[str, str]) -> str | None:
    if not attrs:
        return None
    return json.dumps(attrs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stream_xml_lexemes(
    xml_path: Path, source: str, language: str, synth: LemmaSynthesizer, buf: _Buffers
) -> None:
    current_paradigm_id: int | None = None

    context = etree.iterparse(str(xml_path), events=("start", "end"))
    for event, elem in context:
        if event == "start" and elem.tag == "Paradigm":
            pid = elem.attrib.get("ID")
            current_paradigm_id = int(pid) if pid is not None else None
        elif event == "end" and elem.tag == "Lexeme":
            a = elem.attrib
            attrs = _norm_attrs(elem)
            stem1 = a.get("Stem1")
            stem2 = a.get("Stem2")
            stem3 = a.get("Stem3")
            lemma = attrs.pop("Pamatforma", None) or synth.synthesize(
                language, current_paradigm_id, stem1
            )
            lex_id = a.get("ID")
            buf.append(
                lexeme_id=int(lex_id) if lex_id is not None else None,
                entry_id=None,  # legacy XMLs don't carry entry IDs
                human_id=None,
                paradigm_id=current_paradigm_id,
                paradigm_name=None,  # filled in post-pass via paradigm_id join
                lemma=lemma,
                stem1=stem1,
                stem2=stem2,
                stem3=stem3,
                attributes_json=_attrs_to_json(attrs),
                source=source,
                language=language,
            )
            elem.clear()
            # Also drop preceding siblings to keep the parent's child list short.
            while elem.getprevious() is not None:
                del elem.getparent()[0]
        elif event == "end" and elem.tag == "Paradigm":
            current_paradigm_id = None
            elem.clear()


def _stream_jsonl(jsonl_path: Path, source: str, language: str, buf: _Buffers) -> None:
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            attrs = d.get("attributes") or {}
            buf.append(
                lexeme_id=d.get("lexeme_id"),
                entry_id=d.get("entry_id"),
                human_id=d.get("human_id"),
                paradigm_id=None,  # JSONL only carries paradigm_name
                paradigm_name=d.get("paradigm_name"),
                lemma=d.get("lemma"),
                stem1=None,
                stem2=None,
                stem3=None,
                attributes_json=_attrs_to_json(attrs) if isinstance(attrs, dict) else None,
                source=source,
                language=language,
            )


def _backfill_paradigm_names(
    paradigms_json: Path,
    paradigm_id_col: list[int | None],
    paradigm_name_col: list[str | None],
    language_col: list[str],
) -> None:
    """For XML rows that have paradigm_id but no name, look up name from paradigms.json.

    Keyed by (language, id) since paradigm IDs aren't globally unique.
    """
    with paradigms_json.open(encoding="utf-8") as f:
        data = json.load(f)
    name_by_lang_id = {(p["language"], p["id"]): p["name"] for p in data["paradigms"]}
    for i, (pid, name, lang) in enumerate(
        zip(paradigm_id_col, paradigm_name_col, language_col, strict=True)
    ):
        if name is None and pid is not None:
            paradigm_name_col[i] = name_by_lang_id.get((lang, pid))


def _to_arrow_table(buf: _Buffers) -> pa.Table:
    schema = pa.schema(
        [
            ("lexeme_id", pa.int64()),
            ("entry_id", pa.int64()),
            ("human_id", pa.string()),
            ("paradigm_id", pa.int32()),
            ("paradigm_name", pa.string()),
            ("lemma", pa.string()),
            ("stem1", pa.string()),
            ("stem2", pa.string()),
            ("stem3", pa.string()),
            ("attributes_json", pa.string()),
            ("source", pa.string()),
            ("language", pa.string()),
        ]
    )
    return pa.table(
        {
            "lexeme_id": buf.lexeme_id,
            "entry_id": buf.entry_id,
            "human_id": buf.human_id,
            "paradigm_id": buf.paradigm_id,
            "paradigm_name": buf.paradigm_name,
            "lemma": buf.lemma,
            "stem1": buf.stem1,
            "stem2": buf.stem2,
            "stem3": buf.stem3,
            "attributes_json": buf.attributes_json,
            "source": buf.source,
            "language": buf.language,
        },
        schema=schema,
    )


def extract_lexemes(
    resources_dir: Path, paradigms_json: Path, out_path: Path, *, log: IO[str] | None = None
) -> int:
    """Extract all lexemes to a single Parquet file. Returns row count."""
    synth = LemmaSynthesizer.from_paradigms_json(paradigms_json)
    buf = _Buffers()

    def _log(msg: str) -> None:
        if log is not None:
            log.write(msg + "\n")
            log.flush()

    for filename, source_label, language in XML_SOURCES:
        before = len(buf)
        _stream_xml_lexemes(resources_dir / filename, source_label, language, synth, buf)
        _log(f"  {source_label:>12} ({language})  +{len(buf) - before:>7} lexemes  [{filename}]")

    for filename, source_label, language in JSONL_SOURCES:
        before = len(buf)
        _stream_jsonl(resources_dir / filename, source_label, language, buf)
        _log(f"  {source_label:>12} ({language})  +{len(buf) - before:>7} lexemes  [{filename}]")

    _backfill_paradigm_names(paradigms_json, buf.paradigm_id, buf.paradigm_name, buf.language)

    table = _to_arrow_table(buf)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        out_path,
        compression="zstd",
        compression_level=9,
        use_dictionary=["source", "language", "paradigm_name"],
    )
    return len(buf)


def iter_lexemes_jsonl(jsonl_path: Path) -> Iterator[dict]:
    """Helper for ad-hoc JSONL reads outside of extraction. Not used by the writer."""
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
