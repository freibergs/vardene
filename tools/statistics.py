"""Extract corpus frequency statistics from Statistics.xml.

Two flat tables:
  - ending_frequencies: {ending_id (int) → count (int)}, ~1100 entries
  - lexeme_frequencies: {lexeme_id (int) → count (int)}, ~10K entries

The morphotagger uses these to disambiguate between equally valid
morphological analyses. Without them, the tagger picks arbitrarily.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from lxml import etree


@dataclass(slots=True)
class Statistics:
    ending_frequencies: dict[int, int]
    lexeme_frequencies: dict[int, int]


_ENDING_PREFIX = "Galotne_"


def parse_statistics(xml_path: Path) -> Statistics:
    root = etree.parse(str(xml_path)).getroot()

    ending_block = root.find("Galotņu_biežums")
    ending_freq: dict[int, int] = {}
    if ending_block is not None:
        for key, val in ending_block.attrib.items():
            if key.startswith(_ENDING_PREFIX):
                ending_freq[int(key[len(_ENDING_PREFIX):])] = int(val)

    lex_block = root.find("Leksēmu_biežums")
    lex_freq: dict[int, int] = {}
    if lex_block is not None:
        for child in lex_block.iterfind("Leksēma"):
            lex_freq[int(child.attrib["id"])] = int(child.attrib["count"])

    return Statistics(ending_frequencies=ending_freq, lexeme_frequencies=lex_freq)


def write_statistics(stats: Statistics, out_path: Path) -> None:
    # JSON object keys must be strings — we deliberately serialize int keys as strings.
    payload = {
        "ending_frequencies": {str(k): v for k, v in stats.ending_frequencies.items()},
        "lexeme_frequencies": {str(k): v for k, v in stats.lexeme_frequencies.items()},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
