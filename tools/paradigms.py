"""Extract paradigms + endings + global prefixes from Lexicon_v2.xml.

The XML attribute names use underscores (XML constraint) but the live API
emits spaces. We normalize underscores → spaces in attribute keys so our
output matches `api.vardene.lv` JSON one-to-one.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree


def _norm_key(key: str) -> str:
    """`Lietvārda_tips` → `Lietvārda tips` (matches live API)."""
    return key.replace("_", " ")


def _grammar_attrs(elem: etree._Element) -> dict[str, str]:
    """Read the inner <Attributes ... /> child as a normalized dict."""
    child = elem.find("Attributes")
    if child is None:
        return {}
    return {_norm_key(k): v for k, v in child.attrib.items()}


@dataclass(slots=True)
class Ending:
    id: int
    ending: str
    stem_change: int
    stem_id: int
    lemma_ending_id: int | None
    do_not_generate: bool
    language_normalization: str | None
    attributes: dict[str, str]


@dataclass(slots=True)
class Paradigm:
    id: int
    name: str | None
    language: str  # "lv" or "ltg"
    stems: int
    lemma_ending_id: int
    description: str | None
    description_en: str | None
    allowed_guess_endings: str | None
    attributes: dict[str, str]
    endings: list[Ending] = field(default_factory=list)


@dataclass(slots=True)
class LanguagePrefixes:
    """Per-language prefix lists (negation/debitive/superlative/verb)."""

    language: str
    negation: list[str] = field(default_factory=list)
    debitive: list[str] = field(default_factory=list)
    superlative: list[str] = field(default_factory=list)
    verb: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParadigmBundle:
    """Top-level container: paradigms + per-language prefixes + core file refs."""

    prefixes: list[LanguagePrefixes]
    core_files: list[str]
    paradigms: list[Paradigm]


def _parse_ending(elem: etree._Element) -> Ending:
    a = elem.attrib
    le = a.get("LemmaEnding")
    return Ending(
        id=int(a["ID"]),
        ending=a.get("Ending", ""),
        stem_change=int(a.get("StemChange", "0")),
        stem_id=int(a.get("StemID", "1")),
        lemma_ending_id=int(le) if le is not None else None,
        do_not_generate=a.get("Ģenerēt") == "Nē",
        language_normalization=a.get("Valodas_normēšana"),
        attributes=_grammar_attrs(elem),
    )


def _parse_paradigm(elem: etree._Element, language: str) -> Paradigm:
    a = elem.attrib
    return Paradigm(
        id=int(a["ID"]),
        name=a.get("Name"),
        language=language,
        stems=int(a.get("Stems", "1")),
        lemma_ending_id=int(a["LemmaEnding"]),
        description=a.get("Description"),
        description_en=a.get("DescriptionEN"),
        allowed_guess_endings=a.get("AllowedGuessEndings"),
        attributes=_grammar_attrs(elem),
        endings=[_parse_ending(e) for e in elem.iterfind("Ending")],
    )


def _parse_prefixes(root: etree._Element, language: str) -> LanguagePrefixes:
    out = LanguagePrefixes(language=language)
    block = root.find("Prefixes")
    if block is None:
        return out
    tag_to_attr = {
        "Negation": "negation",
        "Debitive": "debitive",
        "Superlative": "superlative",
        "VerbPrefix": "verb",
    }
    for child in block:
        attr = tag_to_attr.get(str(child.tag))
        if attr and child.text:
            getattr(out, attr).append(child.text.strip())
    # dedupe verb prefixes while preserving order — XML has duplicates ("at" twice)
    out.verb = list(dict.fromkeys(out.verb))
    return out


def parse_paradigms(sources: list[tuple[Path, str]]) -> ParadigmBundle:
    """Parse multiple <Morphology> XMLs (one per language) into a unified bundle.

    `sources` is a list of (xml_path, language_code) pairs. Paradigm IDs are not
    globally unique across languages — consumers should join on (language, id)
    or on the unique paradigm `name` (e.g. "noun-1a" vs "noun-1a-ltg").
    """
    paradigms: list[Paradigm] = []
    prefixes: list[LanguagePrefixes] = []
    core_files: list[str] = []
    for xml_path, language in sources:
        root = etree.parse(str(xml_path)).getroot()
        paradigms.extend(_parse_paradigm(p, language) for p in root.iterfind("Paradigm"))
        prefixes.append(_parse_prefixes(root, language))
        core_files.extend(c.attrib["FileName"] for c in root.iterfind("Corpus"))
    return ParadigmBundle(prefixes=prefixes, core_files=core_files, paradigms=paradigms)


def write_paradigms(bundle: ParadigmBundle, out_path: Path) -> None:
    payload: dict[str, Any] = asdict(bundle)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
