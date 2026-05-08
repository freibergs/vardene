"""Extract tokenizer constants embedded in Splitting.java.

The Java file holds a few critical strings as code-level constants:
  - the separator character class
  - characters stripped before analysis (soft hyphen U+00AD)
  - the temporary marker character (zero-width space U+200B)

We pull them out by regex so we can detect drift if the upstream changes them.
The output is a small JSON file consumed by our Python tokenizer.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class TokenizerConstants:
    separators: str
    soft_hyphen: str  # stripped from words before analysis
    temp_marker: str  # zero-width space, used internally as a tokenizer marker


_DOUBLE_QUOTE = '"'

# Capture: String separators=" \t...";
_SEPARATORS_RE = re.compile(
    r'String\s+separators\s*=\s*' + _DOUBLE_QUOTE + r'(?P<sep>(?:[^' + _DOUBLE_QUOTE + r'\\]|\\.)*)' + _DOUBLE_QUOTE
)


def _decode_java_string(literal: str) -> str:
    """Decode the small subset of Java escapes Splitting.java actually uses."""
    out: list[str] = []
    i = 0
    while i < len(literal):
        c = literal[i]
        if c == "\\" and i + 1 < len(literal):
            nxt = literal[i + 1]
            if nxt == "u" and i + 5 < len(literal):
                out.append(chr(int(literal[i + 2 : i + 6], 16)))
                i += 6
                continue
            if nxt in {"t", "n", "r"}:
                out.append({"t": "\t", "n": "\n", "r": "\r"}[nxt])
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == _DOUBLE_QUOTE:
                out.append(_DOUBLE_QUOTE)
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_tokenizer(splitting_java: Path) -> TokenizerConstants:
    text = splitting_java.read_text(encoding="utf-8")
    m = _SEPARATORS_RE.search(text)
    if m is None:
        raise RuntimeError(f"Could not locate `String separators=...` in {splitting_java}")
    separators = _decode_java_string(m.group("sep"))
    return TokenizerConstants(
        separators=separators,
        soft_hyphen="­",
        temp_marker="​",
    )


def write_tokenizer(c: TokenizerConstants, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(asdict(c), f, ensure_ascii=False, indent=2)
