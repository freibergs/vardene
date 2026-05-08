"""Shared DSL primitives for the LV (`mijas.py`) and LTG (`mijas_ltg.py`)
mija engines.

Keeping these here avoids a circular import between the two language modules.
The pattern: `SuffixRule` rows are *data*, `_apply_first` / `_apply_all` are
the *engine*. A case function says HOW (single yield, multi-yield, with or
without degree wrapping); a rule table says WHAT (which suffix becomes which).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from tezaurs.variants import Variants

# Tag-attribute names + value names referenced by both language modules.
I_DEGREE = "Pakāpe"
I_MIJA = "Mija"
I_NORMATIVE = "Valodas normēšana"
V_POSITIVE = "Pamata"
V_COMPARATIVE = "Pārākā"
V_SUPERLATIVE = "Vispārākā"
V_UNDESIRABLE = "Nevēlams"

_VOWELS: frozenset[str] = frozenset("aāeēiīouū")


@dataclass(frozen=True, slots=True)
class SuffixRule:
    """If a stem ends with `match`, strip those chars and append `replace`."""

    match: str
    replace: str
    note: str = ""  # documentation, kept with the data


def _apply_first(celms: str, rules, *attrs) -> Iterator[Variants]:
    """Yield ONE variant from the first matching rule."""
    for r in rules:
        if celms.endswith(r.match):
            new = celms[: -len(r.match)] + r.replace if r.match else celms + r.replace
            yield Variants(new, *attrs)
            return


def _apply_all(celms: str, rules, *attrs) -> Iterator[Variants]:
    """Yield a variant for EVERY matching rule."""
    for r in rules:
        if celms.endswith(r.match):
            new = celms[: -len(r.match)] + r.replace if r.match else celms + r.replace
            yield Variants(new, *attrs)


def _strip_vis(celms: str) -> tuple[str, str]:
    """Split off the LV `vis-` superlative prefix; returns (stem, degree)."""
    if celms.startswith("vis"):
        return celms[3:], V_SUPERLATIVE
    return celms, V_COMPARATIVE


def _strip_vys(celms: str) -> tuple[str, str]:
    """Split off the LTG `vys`/`vysu` superlative prefix."""
    if celms.startswith("vysu"):
        return celms[4:], V_SUPERLATIVE
    if celms.startswith("vys"):
        return celms[3:], V_SUPERLATIVE
    return celms, V_COMPARATIVE


def syllables(word: str) -> int:
    """Approximate syllable count: count of vowel-onsets in `word`.

    Used by LV case 17 (short feminine vocative form like 'kristīnīt').
    """
    counter = 0
    in_vowel = False
    for c in word:
        if not in_vowel and c in _VOWELS:
            counter += 1
        in_vowel = c in _VOWELS
    return counter
