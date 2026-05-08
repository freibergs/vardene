"""Extract the morphological tagset from TagSet.xml.

`TagSet.xml` is the canonical source: 97 grammatical attributes (LV+EN names,
which POS they apply to, position in the compact markup tag), each with values
(LV name, EN name, single-char tag, optional default tag string, optional GF tag).

`TagSet.json` shipped in the repo only captures the POS-dispatch decision tree —
not enough for our needs.

The 24 `<FreeAttribute>` entries are bookkeeping fields (lexeme ID, paradigm ID,
free-text descriptions) that don't appear in compact markup.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree


@dataclass(slots=True)
class TagValue:
    lv: str
    en: str | None
    tag: str | None
    default_tags: str | None
    gf: str | None


@dataclass(slots=True)
class TagAttribute:
    lv: str
    en: str | None
    description: str | None
    part_of_speech: str | None
    markup_pos: int | None
    gf: str | None
    values: list[TagValue] = field(default_factory=list)


@dataclass(slots=True)
class TagSet:
    attributes: list[TagAttribute]
    free_attributes: list[dict[str, str]]
    # Reverse indexes for fast lookup. Computed on extraction so consumers don't.
    by_lv: dict[str, int] = field(default_factory=dict)  # LV name → index into attributes
    pos_to_attrs: dict[str, list[int]] = field(default_factory=dict)  # POS LV → attr indexes


def _parse_value(elem: etree._Element) -> TagValue:
    a = elem.attrib
    return TagValue(
        lv=a["LV"],
        en=a.get("EN"),
        tag=a.get("Tag"),
        default_tags=a.get("DefaultTags"),
        gf=a.get("GF"),
    )


def _parse_attribute(elem: etree._Element) -> TagAttribute:
    a = elem.attrib
    markup_pos = a.get("MarkupPos")
    return TagAttribute(
        lv=a["LV"],
        en=a.get("EN"),
        description=a.get("Description"),
        part_of_speech=a.get("PartOfSpeech"),
        markup_pos=int(markup_pos) if markup_pos is not None else None,
        gf=a.get("GF"),
        values=[_parse_value(v) for v in elem.iterfind("Value")],
    )


def parse_tagset(xml_path: Path) -> TagSet:
    root = etree.parse(str(xml_path)).getroot()
    attrs = [_parse_attribute(a) for a in root.iterfind("Attribute")]
    free = [dict(f.attrib) for f in root.iterfind("FreeAttribute")]

    by_lv = {a.lv: i for i, a in enumerate(attrs)}
    pos_to_attrs: dict[str, list[int]] = {}
    for i, a in enumerate(attrs):
        if a.part_of_speech:
            pos_to_attrs.setdefault(a.part_of_speech, []).append(i)
    return TagSet(attributes=attrs, free_attributes=free, by_lv=by_lv, pos_to_attrs=pos_to_attrs)


def write_tagset(ts: TagSet, out_path: Path) -> None:
    payload: dict[str, Any] = asdict(ts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
