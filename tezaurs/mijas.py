"""Mijas — stem alternations engine. Port of `analyzer/Mijas.java` (1879 LOC).

Two paired entry points, both keyed on a `stem_change` ID (0–38 LV core,
99–127 LTG core, 4/5/12/19/28/29/31/37 + 150–167 are prefix-redirect aliases):

  * `mija_variants(stem, stem_change, proper_name)` — analysis direction:
    given a SURFACE stem and the stem-change ID for its ending, return all
    plausible base-form stems ("celms") that could have produced it.

  * `mija_for_inflection(stem, stem_change, third_stem, add_superlative,
    proper_name)` — generation direction: given a BASE stem and the
    stem-change ID for the target ending, return all surface stems.

The Java switch-cases are ported one-for-one. A handful of cases that only
strip a debitive/Latgalian prefix and redirect to another mija are extracted
into the `_PREFIX_REDIRECTS` data table — that compresses ~120 lines of Java
into a small dict.

Code-as-code (not code-as-data): the actual transformation logic stays as
Python because the rules are too context-sensitive (depend on stem length,
ending characters, lexical exceptions like "vajadzēt" → "vajag") to fit a
clean declarative form.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

from tezaurs.attributes import AttributeValues
from tezaurs.variants import Variants


# ---------------------------------------------------------------------------
# Constants from `attributes/AttributeNames.java` that this module references.
# ---------------------------------------------------------------------------

I_DEGREE = "Pakāpe"
I_MIJA = "Mija"
I_NORMATIVE = "Valodas normēšana"
V_POSITIVE = "Pamata"
V_COMPARATIVE = "Pārākā"
V_SUPERLATIVE = "Vispārākā"
V_UNDESIRABLE = "Nevēlams"

_VOWELS: frozenset[str] = frozenset("aāeēiīouū")


# ---------------------------------------------------------------------------
# Matrix-driven case dispatcher.
#
# A case spec is a list of operations applied in order. Each operation either
# yields zero or more `Variants` or transforms `celms`/`degree` for subsequent
# operations.
#
#   Rule format:  (match, transform, *attrs)
#     match:      str (endswith) | tuple[str] (endswith-any) | None (always)
#     transform:  ""        — yield celms as-is
#                 "+xy"     — yield celms + "xy"
#                 "-N"      — yield celms[:-N]
#                 "-N+xy"   — yield celms[:-N] + "xy"
#                 callable  — `fn(celms) -> str`
#     attrs:      forwarded to Variants(...)
#
#   Operations:
#     ("ELIF", [rules...])    first matching rule fires; rest of operations skipped
#     ("MULTI", [rules...])   every matching rule fires (independent)
#     ("DEFAULT", rule)       fires only if no earlier op produced output
#     ("LEN_GT", n)           abort case if len(celms) <= n
#     ("MATCH", suffix)       abort case unless celms.endswith(suffix)
#     ("NOT_MATCH", suffix)   abort case if celms.endswith(suffix)
#     ("STRIP_LV_VIS",)       strip "vis-" prefix; sets degree=V_SUPERLATIVE,
#                             else V_COMPARATIVE. Subsequent rules can use
#                             (..., I_DEGREE, "{DEG}") to splice degree.
#     ("STRIP_LTG_VYS",)      strip "vysu"/"vys"; degree=V_SUPERLATIVE,
#                             else V_COMPARATIVE. Then rules emit `_ltg_degree_flags`.
# ---------------------------------------------------------------------------


def _apply_transform(celms: str, transform) -> str:
    """Apply transform spec to celms and return new stem."""
    if callable(transform):
        return transform(celms)
    if not transform:
        return celms
    rest = transform
    strip = 0
    if rest.startswith("-"):
        i = 1
        while i < len(rest) and rest[i].isdigit():
            i += 1
        strip = int(rest[1:i]) if i > 1 else 0
        rest = rest[i:]
    if rest.startswith("+"):
        rest = rest[1:]
    return (celms[:-strip] if strip else celms) + rest


def _expand_attrs(attrs, degree):
    """Substitute the degree placeholder in attrs."""
    if not attrs:
        return attrs
    out = []
    for a in attrs:
        if a == "{DEG}":
            out.append(degree)
        else:
            out.append(a)
    return tuple(out)


def _matches(celms: str, suffix) -> bool:
    if suffix is None:
        return True
    return celms.endswith(suffix)


def _emit(celms, tr, attrs, degree, ltg_degree):
    """Build one Variants, applying transform and degree-handling rules."""
    new = _apply_transform(celms, tr)
    if ltg_degree and degree != V_POSITIVE:
        return Variants(new, attributes=_ltg_degree_flags(degree))
    extra = _expand_attrs(attrs, degree)
    return Variants(new, *extra)


def _fire_rule(celms, rule, degree, ltg_degree) -> Iterator[Variants]:
    """A rule's transform may be a list (multi-yield). Otherwise single yield."""
    _, tr, *attrs = rule
    if isinstance(tr, list):
        for sub in tr:
            sub_tr, *sub_attrs = sub
            yield _emit(celms, sub_tr, sub_attrs, degree, ltg_degree)
    else:
        yield _emit(celms, tr, attrs, degree, ltg_degree)


def _run_case(celms: str, ops, *, ltg_degree: bool = False) -> Iterator[Variants]:
    """Execute a case spec. Tracks `degree` for vis-/vys- wrapping; emits
    Variants with the degree spliced into matching attrs slots."""
    degree = V_POSITIVE
    yielded_anything = False
    for op in ops:
        kind = op[0]
        if kind == "ELIF":
            for rule in op[1]:
                if _matches(celms, rule[0]):
                    for v in _fire_rule(celms, rule, degree, ltg_degree):
                        yield v
                        yielded_anything = True
                    break
            return  # ELIF terminates the case
        if kind == "MULTI":
            for rule in op[1]:
                if _matches(celms, rule[0]):
                    for v in _fire_rule(celms, rule, degree, ltg_degree):
                        yield v
                        yielded_anything = True
            continue
        if kind == "DEFAULT":
            if not yielded_anything:
                _, tr, *attrs = op
                yield _emit(celms, tr, attrs, degree, ltg_degree)
                yielded_anything = True
            continue
        if kind == "LEN_GT":
            if len(celms) <= op[1]:
                return
            continue
        if kind == "MATCH":
            if not _matches(celms, op[1]):
                return
            continue
        if kind == "NOT_MATCH":
            if _matches(celms, op[1]):
                return
            continue
        if kind == "STRIP_LV_VIS":
            if celms.startswith("vis"):
                celms = celms[3:]
                degree = V_SUPERLATIVE
            else:
                degree = V_COMPARATIVE
            continue
        if kind == "STRIP_LTG_VYS":
            if celms.startswith("vysu"):
                celms = celms[4:]
                degree = V_SUPERLATIVE
            elif celms.startswith("vys"):
                celms = celms[3:]
                degree = V_SUPERLATIVE
            else:
                degree = V_COMPARATIVE
            continue


def syllables(word: str) -> int:
    """Approximate syllable count: count of vowel-onsets in `word`.

    Direct port of the Java `syllables` private helper. Used by case 17
    (short feminine vocative form like 'kristīnīt!', 'margriet!').
    """
    counter = 0
    in_vowel = False
    for c in word:
        if not in_vowel and c in _VOWELS:
            counter += 1
        in_vowel = c in _VOWELS
    return counter


# ---------------------------------------------------------------------------
# Latgalian helpers — used by both directions and by the prefix-redirect table.
# Ported below as standalone functions so the redirect table can reference them.
# ---------------------------------------------------------------------------


# Regex anchored on the last syllable: prefix, vowel/diphthong, then a final
# consonant cluster + optional vowels. Direct port of the Java patterns.
_LTG_FORWARD_RE = re.compile(
    r"(.*?)(ai|ei|ui|oi|ie|[aāeēiīouūy])"
    r"([bcčdfgģhjkķlļmnņprŗsštvzž]+[aāeēiīyoōuū]*)$"
)
_LTG_BACKWARD_RE = re.compile(
    r"(.*?)(uo|[aāeēiīouūy]|)"
    r"([bcčdfgģhjkķlļmnņprŗsštvzž]+[aāeēiīyoōuū]*)$"
)


def _ltg_patskanu_mija_locisanai(celms: str) -> str:
    """Forward Latgalian vowel alternation (`ltgPatskaņuMijaLocīšanai`).

    Maps the syllable-nuclear vowel: a→o, e→a, ē→ā, i→y; other vowels unchanged.
    """
    m = _LTG_FORWARD_RE.match(celms)
    if not m:
        return celms
    pre, vowel, post = m.groups()
    mapping = {"a": "o", "e": "a", "ē": "ā", "i": "y"}
    new_vowel = mapping.get(vowel)
    return f"{pre}{new_vowel}{post}" if new_vowel else celms


def _ltg_patskanu_mija_atpakal_locisanai(celms: str) -> str:
    """Reverse Latgalian vowel alternation (`ltgPatkaņuMijaAtpakaļlocīšanai`).

    Inverse of forward: a→e, ā→ē, y→i, o→a; other vowels (and `uo`) unchanged.
    """
    m = _LTG_BACKWARD_RE.match(celms)
    if not m:
        return celms
    pre, vowel, post = m.groups()
    mapping = {"a": "e", "ā": "ē", "y": "i", "o": "a"}
    new_vowel = mapping.get(vowel)
    return f"{pre}{new_vowel}{post}" if new_vowel else celms


def _ltg_burtu_mija(celms: str) -> str:
    """Forward Latgalian letter alternation (`ltgBurtuMija`).

    Before -e/-i/-ī/-ē/-ie, the soft consonants ļ/ņ/ķ/ģ harden to l/n/k/g.
    Doubled (ļļ/ņņ) collapse to (ll/nn).
    """
    if celms.endswith("ļļ"):
        return celms[:-2] + "ll"
    if celms.endswith("ņņ"):
        return celms[:-2] + "nn"
    if celms.endswith("ļ"):
        return celms[:-1] + "l"
    if celms.endswith("ņ"):
        return celms[:-1] + "n"
    if celms.endswith("ķ"):
        return celms[:-1] + "k"
    if celms.endswith("ģ"):
        return celms[:-1] + "g"
    return celms


def _ltg_burtu_mija_atpakal_viennoz(celms: str) -> str:
    """Unambiguous reverse Latgalian letter alternation (`ltgBurtuMijaAtpakaļViennoz`).

    Inverse of `_ltg_burtu_mija`: l/n/k/g harden back to ļ/ņ/ķ/ģ when the
    surface form is unambiguous.
    """
    if celms.endswith("ll"):
        return celms[:-2] + "ļļ"
    if celms.endswith("nn"):
        return celms[:-2] + "ņņ"
    if celms.endswith("l"):
        return celms[:-1] + "ļ"
    if celms.endswith("n"):
        return celms[:-1] + "ņ"
    if celms.endswith("k"):
        return celms[:-1] + "ķ"
    if celms.endswith("g"):
        return celms[:-1] + "ģ"
    return celms


def _ltg_degree_flags(degree: str) -> AttributeValues:
    """Latgalian degree flags (`ltgDegreeFlags`).

    For Latgalian, superlative made with `vys`/`vysu` is grammatically
    discouraged — it should be analytical with `pots`. We tag it `Nevēlams`.
    """
    av = AttributeValues()
    av.add(I_DEGREE, degree)
    if degree == V_SUPERLATIVE:
        av.add(I_NORMATIVE, V_UNDESIRABLE)
    return av


# ---------------------------------------------------------------------------
# Prefix-redirect table.
#
# These cases all share the same shape: optionally check a prefix (jā- for
# debitive in LV, juo- in LTG), strip it, optionally apply a vowel-mija on
# the residue, then jump to a different mija number.
#
# Format:
#   stem_change_in -> (prefix_or_None, min_length, target_mija, vowel_mija_after_strip)
#
# Java cases collapsed: 4, 5, 12, 19, 28, 29, 31, 37 (LV debitive)
#                      150, 151, 152, 153 (LTG debitive)
#                      160, 161, 162, 163, 164, 165, 166, 167 (LTG vowel-only)
# ---------------------------------------------------------------------------

_PREFIX_REDIRECTS: dict[int, tuple[str | None, int, int, bool]] = {
    # LV debitive: jā- prefix, 4-char minimum, redirect to underlying mija
    4:  ("jā", 4, 0,  False),
    5:  ("jā", 4, 9,  False),
    12: ("jā", 4, 8,  False),
    19: ("jā", 4, 2,  False),
    28: ("jā", 4, 20, False),
    29: ("jā", 4, 27, False),
    31: ("jā", 4, 30, False),
    37: ("jā", 4, 36, False),
    # LTG debitive: juo- prefix, 5-char minimum
    150: ("juo", 5, 110, False),
    151: ("juo", 5, 119, True),
    152: ("juo", 5, 122, True),
    153: ("juo", 5, 125, False),
    # LTG vowel-mija only (no prefix to strip)
    160: (None, 0, 114, True),
    161: (None, 0, 116, True),
    162: (None, 0, 119, True),
    163: (None, 0, 120, True),
    164: (None, 0, 122, True),
    165: (None, 0, 123, True),
    166: (None, 0, 124, True),
    167: (None, 0, 126, True),
}


def _resolve_redirect(stem: str, stem_change: int) -> tuple[str, int] | None:
    """Apply the prefix-redirect table. Returns (residual_celms, target_mija)
    if redirected, or None if no redirect / prerequisites failed."""
    rule = _PREFIX_REDIRECTS.get(stem_change)
    if rule is None:
        return None
    prefix, min_len, target, vowel_mija = rule
    if prefix is None:
        # Pure vowel-mija (cases 160-167): no prefix strip
        return _ltg_patskanu_mija_atpakal_locisanai(stem), target
    # Prefix strip with min-length guard (cases 4-37 LV, 150-153 LTG)
    if stem.startswith(prefix) and len(stem) >= min_len:
        residue = stem[len(prefix):]
        if vowel_mija:
            residue = _ltg_patskanu_mija_atpakal_locisanai(residue)
        return residue, target
    return None  # signals "redirect prerequisites failed"


# ---------------------------------------------------------------------------
# `mija_variants` per-case handlers (analysis direction).
#
# Each handler yields zero or more `Variants` objects. Handler signature:
#   _case_N(celms: str, proper_name: bool) -> Iterator[Variants]
#
# We pass `proper_name` even when unused — the dispatcher is simpler this way.
# ---------------------------------------------------------------------------


def _case_0(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """No mija."""
    yield Variants(celms)


def _case_1(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Noun consonant mija. Java case 1."""
    if celms.endswith("š"):
        if celms.endswith("kš"):
            yield Variants(celms[:-2] + "kst", I_MIJA, "kst -> kš")
        if celms.endswith("nš"):
            yield Variants(celms[:-2] + "nst", I_MIJA, "nst -> nš")
        yield Variants(celms[:-1] + "s", I_MIJA, "s -> š")
        yield Variants(celms[:-1] + "t", I_MIJA, "t -> š")
    elif celms.endswith("ž"):
        yield Variants(celms[:-1] + "z", I_MIJA, "z -> ž")
        yield Variants(celms[:-1] + "d", I_MIJA, "d -> ž")
    elif celms.endswith("č"):
        yield Variants(celms[:-1] + "c", I_MIJA, "c -> č")
    elif celms.endswith("ļ"):
        if celms.endswith("šļ"):
            yield Variants(celms[:-2] + "sl", I_MIJA, "sl -> šļ")
        elif celms.endswith("žļ"):
            yield Variants(celms[:-2] + "zl", I_MIJA, "zl -> žļ")
        elif celms.endswith("ļļ"):
            yield Variants(celms[:-2] + "ll", I_MIJA, "ll -> ļļ")
        else:
            yield Variants(celms[:-1] + "l", I_MIJA, "l -> ļ")
    elif celms.endswith("ņ"):
        if celms.endswith("šņ"):
            yield Variants(celms[:-2] + "sn", I_MIJA, "sn -> šņ")
        elif celms.endswith("žņ"):
            yield Variants(celms[:-2] + "zn", I_MIJA, "zn -> žņ")
        elif celms.endswith("ļņ"):
            yield Variants(celms[:-2] + "ln", I_MIJA, "ln -> ļņ")
        elif celms.endswith("ņņ"):
            yield Variants(celms[:-2] + "nn", I_MIJA, "nn -> ņņ")
        elif not celms.endswith(("zņ", "sņ", "lņ")):
            yield Variants(celms[:-1] + "n", I_MIJA, "n -> ņ")
    elif celms.endswith("j"):
        if celms.endswith(("pj", "bj", "mj", "vj", "fj")):
            yield Variants(celms[:-1], I_MIJA, "p->pj (u.c.)")
        else:
            yield Variants(celms)
    elif not celms.endswith(("p", "b", "m", "v", "t", "d", "c", "z", "s", "n", "l", "f")):
        yield Variants(celms)


def _case_2(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Verb 3rd-conjugation no-mija forms that drop the stem's last char."""
    yield Variants(celms + "ā")
    yield Variants(celms + "ī")
    yield Variants(celms + "ē")


def _case_3(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Adjective comparative -āk- / superlative vis-."""
    if celms.endswith("āk") and len(celms) > 3:
        if celms.startswith("vis"):
            yield Variants(celms[3:-2], I_DEGREE, V_SUPERLATIVE)
        yield Variants(celms[:-2], I_DEGREE, V_COMPARATIVE)
    yield Variants(celms, I_DEGREE, V_POSITIVE)


def _case_6(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """1st-conjugation future."""
    if celms.endswith(("dī", "tī", "sī")):
        yield Variants(celms[:-2] + "s")
    elif celms.endswith("šī"):
        yield Variants(celms[:-1])  # lūzt, griezt
    elif celms.endswith("zī"):
        yield Variants(celms[:-1])  # lūzt, griezt
        yield Variants(celms)  # atzīšos
    elif not celms.endswith(("d", "t", "s", "z")):
        yield Variants(celms)


def _case_7_or_23(celms: str, _proper_name: bool, mija: int) -> Iterator[Variants]:
    """1st-conjugation 2nd-person present (case 7), or with long ending like -iet (case 23)."""
    if celms.endswith("s"):
        yield Variants(celms[:-1] + "š")  # pievēršu -> pievērs
        yield Variants(celms)  # atnest -> atnes
    elif mija == 7 and celms.endswith(("odi", "ūdi", "opi", "ūpi", "oti", "ūti", "īti", "ieti", "sti")):
        yield Variants(celms[:-1])
    elif mija == 23 and celms.endswith(("od", "ūd", "op", "ūp", "ot", "ūt", "īt", "st")):
        yield Variants(celms)
    elif celms.endswith("t"):
        if celms.endswith(("met", "cērt")):
            yield Variants(celms)
        else:
            yield Variants(celms[:-1] + "š")  # pūšu -> pūt, ciešu -> ciet
    elif celms.endswith("d"):
        if celms.endswith(("dod", "ved")) or (celms.endswith("ēd") and not celms.endswith("sēd")):
            yield Variants(celms)
        else:
            yield Variants(celms[:-1] + "ž")  # kožu -> kod
    elif celms.endswith("l"):
        yield Variants(celms[:-1] + "ļ")
    elif not celms.endswith("ņem") and celms.endswith(("m", "b")):
        yield Variants(celms + "j")  # stumju -> stum
    elif celms.endswith("p"):
        yield Variants(celms)  # cep -> cep
        yield Variants(celms + "j")  # cepj -> cep
    elif celms.endswith("c"):
        yield Variants(celms[:-1] + "k")  # raku -> racis
        yield Variants(celms[:-1] + "c")  # veicu -> veicis
    elif celms.endswith("z") and not celms.endswith("dz"):
        yield Variants(celms[:-1] + "ž")
    elif not celms.endswith(("š", "ž", "ļ", "k", "g")):
        yield Variants(celms)


def _case_8(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """-ams/-āms 3rd-conjugation no-mija + we/you forms."""
    if celms.endswith(("inā", "sargā")):
        yield Variants(celms)
    if celms.endswith("ā"):
        yield Variants(celms[:-1] + "ī")
    if celms.endswith("a"):
        yield Variants(celms[:-1] + "ē")
        if not celms.endswith(("ina", "sarga")):
            yield Variants(celms[:-1] + "ā")


def _case_9(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """3rd-conjugation 3rd-person present, no mija."""
    if celms.endswith(("ina", "sarga")):
        yield Variants(celms[:-1] + "ā")
    if celms.endswith("a"):
        yield Variants(celms[:-1] + "ī")
    else:
        yield Variants(celms + "ē")
        yield Variants(celms + "ā")
        yield Variants(celms + "o")  # plīvot -> plīv


def _case_10(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Adjective -āk-/vis-, -i adverb form."""
    if celms.endswith("i"):
        yield Variants(celms[:-1], I_DEGREE, V_POSITIVE)
    if celms.endswith("āk"):
        if celms.startswith("vis"):
            yield Variants(celms[3:-2], I_DEGREE, V_SUPERLATIVE)
        else:
            yield Variants(celms[:-2], I_DEGREE, V_COMPARATIVE)


def _case_11(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """-uša + 1st-conj definite forms: veicu→veikušais, beidzu→beigušais, etc."""
    if not celms.endswith("c") and not celms.endswith("dz"):
        yield Variants(celms)
    if celms.endswith("k"):
        yield Variants(celms[:-1] + "c")
    if celms.endswith("g"):
        yield Variants(celms[:-1] + "dz")


def _case_13(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Adjective -āk-/vis- with š→s in nominative (zaļš → zaļāks)."""
    if celms.endswith("āk"):
        if celms.startswith("vis"):
            yield Variants(celms[3:-2], I_DEGREE, V_SUPERLATIVE)
        else:
            yield Variants(celms[:-2], I_DEGREE, V_COMPARATIVE)


_RULES_14 = [("ELIF", [
    ("c",  [("-1+k",), ("-1+c",)]),
    ("dz", [("-2+g",), ("",)]),
    (None, ""),  # default: yield unchanged
])]
def _case_14(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """1st-conjugation -is form."""
    yield from _run_case(celms, _RULES_14)


_RULES_15 = [("MULTI", [
    (None, ""),         # always yield unchanged
    ("z",  "-1+s"),     # also yield s-variant if z stem
])]
def _case_15(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """pūst → pūzdams, nopūzdamies — s↔z mija."""
    yield from _run_case(celms, _RULES_15)


def _case_16(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """1st-conjugation -šana derivation."""
    if not celms.endswith(("s", "z")):
        yield Variants(celms)
        yield Variants(celms + "s")  # nest -> nešana
        yield Variants(celms + "z")  # mēzt -> mēšana


def _case_17(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Short feminine vocative: 'kristīnīt!', 'margriet!'."""
    if syllables(celms) >= 2 or celms.endswith(("iņ", "īt")):
        yield Variants(celms)


def _case_20(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """3rd-conjugation present mija for 1st-person present, -ot participle, debitive.
    Differs from case 26 ('gulēt' and 'tecēt')."""
    if celms.endswith(("guļ", "gul")):
        yield Variants(celms[:-1] + "lē")  # gulēt -> guļošs and also gulošs
    if celms.endswith("k"):
        yield Variants(celms[:-1] + "cī")  # sacīt -> saku
        yield Variants(celms[:-1] + "cē")  # mācēt -> māku
    elif celms.endswith("g"):
        yield Variants(celms[:-1] + "dzī")  # slodzīt -> slogu
        yield Variants(celms[:-1] + "dzē")  # vajadzēt -> vajag
    elif celms.endswith("ž"):
        yield Variants(celms[:-1] + "dē")  # sēdēt -> sēžu
    if celms.endswith(("loc", "moc", "urc")):
        yield Variants(celms + "ī")  # alternative form


def _case_21(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """-is/-ušais comparative and superlative — visizkusušākais saldējums."""
    if celms.startswith("vis"):
        yield Variants(celms[3:], I_DEGREE, V_SUPERLATIVE)
    else:
        yield Variants(celms, I_DEGREE, V_COMPARATIVE)


def _case_22(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """jaundzimušais → jaundzimusī."""
    if celms.endswith("us"):
        yield Variants(celms[:-2] + "uš")


def _case_24(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Like case 2 but for comparative/superlative — visizsakošākais."""
    pakape = V_COMPARATIVE
    if celms.startswith("vis"):
        pakape = V_SUPERLATIVE
        celms = celms[3:]
    yield Variants(celms + "ā", I_DEGREE, pakape)
    yield Variants(celms + "ī", I_DEGREE, pakape)
    yield Variants(celms + "ē", I_DEGREE, pakape)


def _case_25(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Like case 8 but for comparative/superlative -amāks forms."""
    pakape = V_COMPARATIVE
    if celms.startswith("vis"):
        pakape = V_SUPERLATIVE
        celms = celms[3:]
    if celms.endswith(("inā", "sargā")):
        yield Variants(celms, I_DEGREE, pakape)
    if celms.endswith("ā"):
        yield Variants(celms[:-1] + "ī", I_DEGREE, pakape)
    elif celms.endswith("a"):
        yield Variants(celms[:-1] + "ē", I_DEGREE, pakape)
        if not celms.endswith(("ina", "sarga")):
            yield Variants(celms[:-1] + "ā", I_DEGREE, pakape)


def _case_26(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """3rd-conjugation mija forms — 2nd-person present, imperative."""
    if celms.endswith("gul"):
        yield Variants(celms[:-1] + "lē")  # guli -> gulēt
    if celms.endswith("tec"):
        yield Variants(celms + "ē")  # teci -> tecēt
    elif celms.endswith("k") and not celms.endswith("tek"):
        yield Variants(celms[:-1] + "cī")  # saki -> sacīt
        yield Variants(celms[:-1] + "cē")  # māki -> mācēt
    elif celms.endswith("g"):
        yield Variants(celms[:-1] + "dzī")  # slogi -> slodzīt
        yield Variants(celms[:-1] + "dzē")  # vajag -> vajadzēt
    elif celms.endswith(("loc", "moc", "urc")):
        yield Variants(celms + "ī")  # alternative form
    else:
        yield Variants(celms + "ē")  # sēdies -> sēdēties


def _case_27(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """-ams/-āms 3rd-conjugation mija + we/you forms."""
    if celms.endswith("kā"):
        yield Variants(celms[:-2] + "cī")  # sacīt
    elif celms.endswith("gā"):
        yield Variants(celms[:-2] + "dzī")  # slodzīt -> slogu
    elif celms.endswith("ka"):
        yield Variants(celms[:-2] + "cē")  # mācēt -> mākam
    elif celms.endswith("ža"):
        yield Variants(celms[:-2] + "dē")  # sēdēt -> sēžam
    elif celms.endswith("ļa"):
        yield Variants(celms[:-2] + "lē")  # gulēt -> guļam
    elif celms.endswith("ga"):
        yield Variants(celms[:-2] + "dzē")  # vajadzēt -> vajag


def _case_30(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """3rd-conjugation 3rd-person present with mija."""
    if celms.endswith("vajadz"):
        return  # exception: 'vajadzēt' -> 'vajag' is correct
    if celms.endswith("ka"):
        yield Variants(celms[:-2] + "cī")  # sacīt
    elif celms.endswith("ga"):
        yield Variants(celms[:-2] + "dzī")  # slodzīt -> sloga
    elif celms.endswith("k"):
        yield Variants(celms[:-1] + "cē")  # mācēt -> māk
    elif celms.endswith("ž"):
        yield Variants(celms[:-1] + "dē")  # sēdēt -> sēž
    elif celms.endswith("ļ"):
        yield Variants(celms[:-1] + "lē")  # 'guļ' -> 'gulēt'
    elif celms.endswith("vajag"):
        yield Variants(celms[:-1] + "dzē")  # vajadzēt -> vajag


def _case_32(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Like case 20 but for comparative/superlative — visizsakošākais."""
    pakape = V_COMPARATIVE
    if celms.startswith("vis"):
        pakape = V_SUPERLATIVE
        celms = celms[3:]
    if celms.endswith("k"):
        yield Variants(celms[:-1] + "cī", I_DEGREE, pakape)  # sacīt -> sakošākais
        yield Variants(celms[:-1] + "cē", I_DEGREE, pakape)  # mācēt -> mākošākais
    elif celms.endswith("g"):
        yield Variants(celms[:-1] + "dzī", I_DEGREE, pakape)  # slodzīt -> slogošākais
        yield Variants(celms[:-1] + "dzē", I_DEGREE, pakape)  # vajadzēt -> vajagošākais
    elif celms.endswith("ž"):
        yield Variants(celms[:-1] + "dē", I_DEGREE, pakape)  # sēdēt -> sēžu
    elif celms.endswith("ļ"):
        yield Variants(celms[:-1] + "lē", I_DEGREE, pakape)  # gulēt -> guļošākais


def _case_33(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Like case 27 but with comparative/superlative degrees for -amāks forms."""
    pakape = V_COMPARATIVE
    if celms.startswith("vis"):
        pakape = V_SUPERLATIVE
        celms = celms[3:]
    if celms.endswith("kā"):
        yield Variants(celms[:-2] + "cī", I_DEGREE, pakape)  # sacīt
    elif celms.endswith("gā"):
        yield Variants(celms[:-2] + "dzī", I_DEGREE, pakape)  # slodzīt -> slogu
    elif celms.endswith("ka"):
        yield Variants(celms[:-2] + "cē", I_DEGREE, pakape)  # mācēt -> mākam
    elif celms.endswith("ga"):
        yield Variants(celms[:-2] + "dzē", I_DEGREE, pakape)  # vajadzēt -> vajag
    elif celms.endswith("ža"):
        yield Variants(celms[:-2] + "dē", I_DEGREE, pakape)  # sēdēt -> sēžam
    elif celms.endswith("guļa"):
        yield Variants(celms[:-2] + "lē", I_DEGREE, pakape)  # gulēt -> guļam


def _case_34(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Adjective -āk-/vis- with -ajam-style endings (zaļš -> zaļ-a-jam, pēdēj-ais -> pēdē-jam/pēdēj-a-jam)."""
    if celms.endswith("āka") and len(celms) > 4:
        if celms.startswith("vis"):
            yield Variants(celms[3:-3], I_DEGREE, V_SUPERLATIVE)
        yield Variants(celms[:-3], I_DEGREE, V_COMPARATIVE)
    if celms.endswith("a"):  # zaļa-jam -> zaļ; pēdēja-jam -> pēdēj
        yield Variants(celms[:-1], I_DEGREE, V_POSITIVE)
    elif celms.endswith("ē"):  # pēdē-jam -> pēdēj
        yield Variants(celms + "j", I_DEGREE, V_POSITIVE)


def _case_35(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Substantivized 'adjective' -ajam endings (no comparative/superlative)."""
    if celms.endswith("a"):
        yield Variants(celms[:-1], I_DEGREE, V_POSITIVE)
    elif celms.endswith("ē"):
        yield Variants(celms + "j", I_DEGREE, V_POSITIVE)


def _case_36(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """'iet' special case — 3rd-person present stem is 'iet' (not 'ej')."""
    yield Variants(celms)
    if celms.endswith("iet"):
        yield Variants(celms[:-3] + "ej")


# ----- Latgalian cases (99–127) ------------------------------------------------


def _case_99(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Half of LTG burtu mija — only for paradigms whose no-mija stem ends soft."""
    yield Variants(_ltg_burtu_mija_atpakal_viennoz(celms), I_MIJA, "ļņķģ -> lnkg")


def _case_100(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG burtu mija — before -e/-i/-ī/-ē/-ie, ļ/ņ/ķ/ģ become l/n/k/g."""
    softened = _ltg_burtu_mija_atpakal_viennoz(celms)
    yield Variants(softened, I_MIJA, "lnkg -> lļnņkķgģ")
    if softened != celms:
        yield Variants(celms, I_MIJA, "lnkg -> lļnņkķgģ")


_RULES_101 = [("ELIF", [
    ("kš", "-2+kst", I_MIJA, "kst -> kš"),
    ("šļ", "-2+sl",  I_MIJA, "sl -> šļ"),
    ("žļ", "-2+zl",  I_MIJA, "zl -> žļ"),
    ("šm", "-2+sm",  I_MIJA, "sm -> šm"),
    ("šņ", "-2+sn",  I_MIJA, "sn -> šņ"),
    ("žņ", "-2+zn",  I_MIJA, "zn -> žņ"),
    ("ļļ", "-2+ll",  I_MIJA, "ll -> ļļ"),
    ("ņņ", "-2+nn",  I_MIJA, "nn -> ņņ"),
    ("č",  "-1+c",   I_MIJA, "c -> č"),
    ("ž",  [("-1+d", I_MIJA, "d -> ž"), ("-1+z", I_MIJA, "z -> ž")]),
    ("š",  [("-1+t", I_MIJA, "t -> š"), ("-1+s", I_MIJA, "s -> š")]),
    ("ķ",  "-1+k", I_MIJA, "k -> ķ"),
    ("ļ",  "-1+l", I_MIJA, "l -> ļ"),
    ("ņ",  "-1+n", I_MIJA, "n -> ņ"),
    (None, ""),  # default: yield unchanged
])]


def _case_101(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG noun consonant mija for ordinary endings."""
    yield from _run_case(celms, _RULES_101)


_RULES_102 = [("ELIF", [
    ("kš", "-2+kst", I_MIJA, "kst -> kš"),
    ("šl", [("-2+šļ", I_MIJA, "šļ -> šl"), ("-2+sl", I_MIJA, "sl -> šl")]),
    ("žl", [("-2+žļ", I_MIJA, "žļ -> žl"), ("-2+zl", I_MIJA, "zl -> žl")]),
    ("šm", [("-2+šm", I_MIJA, "šm -> šm"), ("-2+sm", I_MIJA, "sn -> šn")]),
    ("šn", [("-2+šņ", I_MIJA, "šņ -> šn"), ("-2+sn", I_MIJA, "sn -> šn")]),
    ("žn", [("-2+žņ", I_MIJA, "žņ -> žn"), ("-2+zn", I_MIJA, "zn -> žn")]),
    ("ll", "-2+ļļ", I_MIJA, "ļļ -> ll"),
    ("nn", "-2+ņņ", I_MIJA, "ņņ -> nn"),
    ("č",  "-1+c",  I_MIJA, "c -> č"),
    ("š",  [("-1+t", I_MIJA, "t -> š"), ("-1+s", I_MIJA, "s -> š")]),
    ("ž",  [("-1+d", I_MIJA, "d -> ž"), ("-1+z", I_MIJA, "z -> ž")]),
    ("l",  "-1+ļ", I_MIJA, "ļ -> l"),
    ("n",  "-1+ņ", I_MIJA, "ņ -> n"),
    ("k",  "-1+ķ", I_MIJA, "ķ -> k"),
    ("g",  "-1+ģ", I_MIJA, "ģ -> g"),
    (None, ""),  # default: unchanged
])]


def _case_102(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG noun consonant softening for e/i/ē/ī/ie endings."""
    yield from _run_case(celms, _RULES_102)


_RULES_103 = [
    ("MATCH", "uok"),
    ("LEN_GT", 3),
    ("STRIP_LTG_VYS",),
    ("MULTI", [(None, "-3")]),
]
def _case_103_inner(celms: str, _proper_name: bool) -> Iterator[Variants]:
    yield from _run_case(celms, _RULES_103, ltg_degree=True)


def _case_103(celms: str, proper_name: bool) -> Iterator[Variants]:
    """LTG adjective -uok- + vys-/vysu-."""
    yield from _case_103_inner(celms, proper_name)
    yield Variants(celms, attributes=_ltg_degree_flags(V_POSITIVE))


_RULES_104 = [
    ("MATCH", "uok"),
    ("LEN_GT", 3),
    ("STRIP_LTG_VYS",),
    ("MULTI", [(None, "-3")]),
]
def _case_104(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG adjective -uok- + vys-/vysu-, with burtu mija on positive degree."""
    if celms.endswith("uok") and len(celms) > 3:
        yield from _run_case(celms, _RULES_104, ltg_degree=True)
    else:
        yield Variants(_ltg_burtu_mija_atpakal_viennoz(celms),
                       attributes=_ltg_degree_flags(V_POSITIVE))


_RULES_105_DEGREE = [
    ("MATCH", "uoka"),
    ("LEN_GT", 4),
    ("STRIP_LTG_VYS",),
    ("MULTI", [(None, "-4")]),
]
_RULES_105_POS = [("ELIF", [
    ("a",         "-1"),
    (("ē", "e"),  "+j"),
])]
def _case_105(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Like case 34 for LTG — -uoka with -ajam-style endings."""
    yield from _run_case(celms, _RULES_105_DEGREE, ltg_degree=True)
    # Positive-degree branch fires regardless
    for v in _run_case(celms, _RULES_105_POS):
        v.add(I_DEGREE, V_POSITIVE)
        yield v


_RULES_106 = [
    ("MATCH", "uok"),
    ("LEN_GT", 3),
    ("STRIP_LTG_VYS",),
    ("MULTI", [(None, "-3")]),
]
def _case_106(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG adverb -uok- + vys-/vysu-."""
    yield from _run_case(celms, _RULES_106, ltg_degree=True)


def _case_107(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG burtu mija inverse — when lemma ending is -e/-i/-ī/-ē/-ie."""
    yield Variants(_ltg_burtu_mija(celms))


def _case_108(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG slapnis-style: 107 (burtu mija) + 106 (vys-uok)."""
    if not (celms.endswith("uok") and len(celms) > 3):
        return
    if celms.startswith("vysu"):
        yield Variants(_ltg_burtu_mija(celms[4:-3]),
                       attributes=_ltg_degree_flags(V_SUPERLATIVE))
    elif celms.startswith("vys"):
        yield Variants(_ltg_burtu_mija(celms[3:-3]),
                       attributes=_ltg_degree_flags(V_SUPERLATIVE))
    else:
        yield Variants(_ltg_burtu_mija(celms[:-3]),
                       attributes=_ltg_degree_flags(V_COMPARATIVE))


def _case_109(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG adverbs with degree gradation, no burtu mija."""
    if celms.endswith("uok") and len(celms) > 4:
        if celms.startswith("vysu"):
            base = celms[4:-3]
            for suffix in ("", "i", "a", "ai"):
                yield Variants(base + suffix, attributes=_ltg_degree_flags(V_SUPERLATIVE))
        elif celms.startswith("vys"):
            base = celms[3:-3]
            for suffix in ("", "i", "a", "ai"):
                yield Variants(base + suffix, attributes=_ltg_degree_flags(V_SUPERLATIVE))
        else:
            base = celms[:-3]
            for suffix in ("", "i", "a", "ai"):
                yield Variants(base + suffix, attributes=_ltg_degree_flags(V_COMPARATIVE))
    else:
        yield Variants(celms, attributes=_ltg_degree_flags(V_POSITIVE))


_RULES_110 = [("ELIF", [
    ("e", [("-1+ei", I_MIJA, "ei -> e"), ("-1+ē", I_MIJA, "ē -> e")]),
    ("o", "-1+uo", I_MIJA, "uo -> o"),
])]
def _case_110(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple present mija."""
    yield from _run_case(celms, _RULES_110)


_RULES_111 = [("ELIF", [
    ("uoj", "-1",     I_MIJA, "uo -> uoj"),
    ("ov",  "-2+uo",  I_MIJA, "uo -> ov"),
    ("iej", "-3+ē",   I_MIJA, "ē -> iej"),
    ("ej",  "-2+ie",  I_MIJA, "ei -> ej"),
])]
def _case_111(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple-past 1st/2nd person singular mija."""
    yield from _run_case(celms, _RULES_111)


_RULES_112 = [("ELIF", [
    ("uoj", "-1",    I_MIJA, "uo -> uoj"),
    ("ov",  "-2+uo", I_MIJA, "uo -> ov"),
    ("ēj",  "-1",    I_MIJA, "ē -> ēj"),
    ("ej",  "-2+ie", I_MIJA, "ei -> ej"),
])]
def _case_112(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple-past plural and 3rd-person mija."""
    yield from _run_case(celms, _RULES_112)


_RULES_113 = [("ELIF", [
    ("ie",         "-2+ē", I_MIJA, "ē -> ie"),
    (("uo", "ei"), ""),
])]
def _case_113(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple-future 1st/2nd person singular mija."""
    yield from _run_case(celms, _RULES_113)


_RULES_114 = [("ELIF", [
    ("ā",          "-1+ē", I_MIJA, "ē -> ā"),
    (("uo", "ei"), ""),
])]
def _case_114(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj subjunctive, supinum, passive past (-ts) participle, -dams."""
    yield from _run_case(celms, _RULES_114)


_RULES_115 = [
    ("STRIP_LTG_VYS",),
    ("ELIF", [
        ("e", [("-1+ei",), ("-1+ē",)]),
        ("o", "-1+uo"),
    ]),
]
def _case_115(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj participle superlative + present mija."""
    yield from _run_case(celms, _RULES_115, ltg_degree=True)


_RULES_116 = [
    ("STRIP_LTG_VYS",),
    ("ELIF", [
        ("ā", "-1+ē"),
        (("uo", "ei"), ""),
    ]),
]
def _case_116(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj participle superlative + subjunctive/supinum mija (-ts participle)."""
    yield from _run_case(celms, _RULES_116, ltg_degree=True)


_RULES_117 = [("ELIF", [
    ("uo", ""),
    ("ie", "-2+ē", I_MIJA, "ē -> ie"),
    ("e",  "-1+ie", I_MIJA, "ei -> e"),
])]
def _case_117(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj past mija for -s, -use participle."""
    yield from _run_case(celms, _RULES_117)


_RULES_118 = [
    ("STRIP_LTG_VYS",),
    ("ELIF", [
        ("ie", "-2+ē"),
        ("e",  "-1+ie"),
        ("uo", ""),
    ]),
]
def _case_118(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj participle superlative + past mija for -s, -use."""
    yield from _run_case(celms, _RULES_118, ltg_degree=True)


def _case_119(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -eit, present and past (no consonant mija ever)."""
    yield Variants(celms + "ei", I_MIJA, "ei -> ")


_RULES_120 = [("STRIP_LTG_VYS",), ("MULTI", [(None, "+ei")])]
def _case_120(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -eit no-mija + participle superlative + present/past mija."""
    yield from _run_case(celms, _RULES_120, ltg_degree=True)


_RULES_121 = [("STRIP_LTG_VYS",), ("MULTI", [(None, "")])]
def _case_121(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj participle superlative without mija."""
    yield from _run_case(celms, _RULES_121, ltg_degree=True)


_RULES_122 = [("ELIF", [
    ("ld", "-2+ļdei", I_MIJA, "ļdei -> ld"),
    ("nd", "-2+ņdei", I_MIJA, "ņdei -> nd"),
    ("g",  "-1+dzei", I_MIJA, "dzei -> g"),
    ("k",  "-1+cei",  I_MIJA, "cei -> k"),
    ("ļ",  "-1+lei",  I_MIJA, "lei -> ļ"),
    ("ņ",  "-1+nei",  I_MIJA, "nei -> ņ"),
])]
def _case_122(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -eit, present with consonant mija."""
    yield from _run_case(celms, _RULES_122)


_RULES_123 = [
    ("STRIP_LTG_VYS",),
    ("ELIF", [
        ("ld", "-2+ļdei"),
        ("nd", "-2+ņdei"),
        ("g",  "-1+dzei"),
        ("k",  "-1+cei"),
        ("ļ",  "-1+lei"),
        ("ņ",  "-1+nei"),
    ]),
]
def _case_123(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -eit with consonant mija + participle superlative + present mija."""
    yield from _run_case(celms, _RULES_123, ltg_degree=True)


def _case_124(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -ēt, present and past, no consonant or letter mija."""
    yield Variants(celms + "ē", I_MIJA, "ē -> ")


def _case_125(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -ēt, present without consonant mija but with letter mija."""
    yield Variants(_ltg_burtu_mija(celms) + "ē", I_MIJA, "ē -> ")


_RULES_126 = [("STRIP_LTG_VYS",), ("MULTI", [(None, "+ē")])]
def _case_126(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -ēt no consonant/letter mija + participle superlative + present/past mija."""
    yield from _run_case(celms, _RULES_126, ltg_degree=True)


_RULES_127 = [("STRIP_LTG_VYS",),
              ("MULTI", [(None, lambda c: _ltg_burtu_mija(c) + "ē")])]
def _case_127(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -ēt with inverse letter mija + participle superlative."""
    yield from _run_case(celms, _RULES_127, ltg_degree=True)


def _case_38(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Adverbs with degree gradation."""
    if celms.endswith("āk") and len(celms) > 3:
        if celms.startswith("vis"):
            stem3 = celms[3:-2]
            yield Variants(stem3, I_DEGREE, V_SUPERLATIVE)
            yield Variants(stem3 + "i", I_DEGREE, V_SUPERLATIVE)
            yield Variants(stem3 + "u", I_DEGREE, V_SUPERLATIVE)
        else:
            stem2 = celms[:-2]
            yield Variants(stem2, I_DEGREE, V_COMPARATIVE)
            yield Variants(stem2 + "i", I_DEGREE, V_COMPARATIVE)
            yield Variants(stem2 + "u", I_DEGREE, V_COMPARATIVE)
    else:
        yield Variants(celms, I_DEGREE, V_POSITIVE)


# Cases 7 and 23 share a body. The dispatcher pre-binds the mija number.
def _case_7(celms: str, proper_name: bool) -> Iterator[Variants]:
    return _case_7_or_23(celms, proper_name, mija=7)


def _case_23(celms: str, proper_name: bool) -> Iterator[Variants]:
    return _case_7_or_23(celms, proper_name, mija=23)


_HANDLERS_VARIANTS: dict[int, Callable[[str, bool], Iterator[Variants]]] = {
    0: _case_0,
    1: _case_1,
    2: _case_2,
    3: _case_3,
    6: _case_6,
    7: _case_7,
    8: _case_8,
    9: _case_9,
    10: _case_10,
    11: _case_11,
    13: _case_13,
    14: _case_14,
    15: _case_15,
    16: _case_16,
    17: _case_17,
    20: _case_20,
    21: _case_21,
    22: _case_22,
    23: _case_23,
    24: _case_24,
    25: _case_25,
    26: _case_26,
    27: _case_27,
    30: _case_30,
    32: _case_32,
    33: _case_33,
    34: _case_34,
    35: _case_35,
    36: _case_36,
    38: _case_38,
    # ----- Latgalian core mijas (phase 4c) -----
    99: _case_99,
    100: _case_100,
    101: _case_101,
    102: _case_102,
    103: _case_103,
    104: _case_104,
    105: _case_105,
    106: _case_106,
    107: _case_107,
    108: _case_108,
    109: _case_109,
    110: _case_110,
    111: _case_111,
    112: _case_112,
    113: _case_113,
    114: _case_114,
    115: _case_115,
    116: _case_116,
    117: _case_117,
    118: _case_118,
    119: _case_119,
    120: _case_120,
    121: _case_121,
    122: _case_122,
    123: _case_123,
    124: _case_124,
    125: _case_125,
    126: _case_126,
    127: _case_127,
}


# ---------------------------------------------------------------------------
# Public entry point: analysis direction
# ---------------------------------------------------------------------------


def mija_variants(stem: str, stem_change: int, proper_name: bool = False) -> list[Variants]:
    """Given a surface stem and the stem-change ID for its ending, return all
    plausible base stems (with grammatical attributes attached when relevant).

    Direct port of `Mijas.mijuVarianti`. Java throws on unhandled cases via a
    catch-all; we raise `NotImplementedError` so it's loud during porting.
    """
    if not stem.strip():
        return []

    redirect = _resolve_redirect(stem, stem_change)
    if redirect is not None:
        celms, mija = redirect
    elif stem_change in _PREFIX_REDIRECTS:
        # Prefix prerequisites failed (e.g. word doesn't start with "jā") — bail.
        return []
    else:
        celms, mija = stem, stem_change

    handler = _HANDLERS_VARIANTS.get(mija)
    if handler is None:
        raise NotImplementedError(
            f"mija_variants: case {mija} not yet ported (was stem_change={stem_change})"
        )
    return list(handler(celms, proper_name))


# ---------------------------------------------------------------------------
# `mija_for_inflection` (generation direction) and `verify_back_inflection`
# are pending in Phase 4d/4e.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# `mija_for_inflection` per-case handlers (generation direction).
#
# Mirror image of `mija_variants`: takes a base lemma stem and the target
# ending's stem-change ID, returns surface stems that the ending can attach to.
#
# Handler signature differs from analysis direction — needs `third_stem`
# (past-tense stem) and `add_superlative` flag for several cases.
# ---------------------------------------------------------------------------


def _resolve_redirect_inflection(stem: str, stem_change: int) -> tuple[str, int] | None:
    """Forward direction prefix-redirect: prepend prefix, optionally apply
    forward vowel-mija, then redirect to target mija. Mirror of
    `_resolve_redirect`."""
    rule = _PREFIX_REDIRECTS.get(stem_change)
    if rule is None:
        return None
    prefix, _min_len, target, vowel_mija = rule
    if prefix is None:
        # Pure vowel-mija (cases 160-167)
        return _ltg_patskanu_mija_locisanai(stem), target
    # Prepend prefix; optionally apply forward vowel-mija to stem first
    residue = _ltg_patskanu_mija_locisanai(stem) if vowel_mija else stem
    return prefix + residue, target


def _inf_0(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """No mija — just yield the stem."""
    yield Variants(celms)


def _inf_1(celms: str, _third: str, _supr: bool, proper_name: bool) -> Iterator[Variants]:
    """Noun consonant mija — generation direction. Mirror of analyzer case 1."""
    if proper_name and celms.endswith("t"):
        yield Variants(celms[:-1] + "š", I_MIJA, "t -> š")
    elif proper_name and celms.endswith("d"):
        yield Variants(celms[:-1] + "ž", I_MIJA, "d -> ž")
    elif celms.endswith(("s", "t")):
        if celms.endswith("kst"):
            yield Variants(celms[:-3] + "kš", I_MIJA, "kst -> kš")
        elif celms.endswith("nst"):  # skansts -> skanšu
            yield Variants(celms[:-3] + "nš", I_MIJA, "nst -> nš")
        elif celms.endswith("s"):
            yield Variants(celms[:-1] + "š", I_MIJA, "s -> š")
        elif celms.endswith("t"):
            yield Variants(celms[:-1] + "š", I_MIJA, "t -> š")
    elif celms.endswith("z"):
        yield Variants(celms[:-1] + "ž", I_MIJA, "z -> ž")
    elif celms.endswith("d"):
        yield Variants(celms[:-1] + "ž", I_MIJA, "d -> ž")
    elif celms.endswith("c"):
        yield Variants(celms[:-1] + "č", I_MIJA, "c -> č")
    elif celms.endswith("l"):
        if celms.endswith("sl"):
            yield Variants(celms[:-2] + "šļ", I_MIJA, "sl -> šļ")
        elif celms.endswith("zl"):
            yield Variants(celms[:-2] + "žļ", I_MIJA, "zl -> žļ")
        elif celms.endswith("ll"):
            yield Variants(celms[:-2] + "ļļ", I_MIJA, "ll -> ļļ")
        else:
            yield Variants(celms[:-1] + "ļ", I_MIJA, "l -> ļ")
    elif celms.endswith("n"):
        if celms.endswith("sn"):
            yield Variants(celms[:-2] + "šņ", I_MIJA, "sn -> šņ")
        elif celms.endswith("zn"):
            yield Variants(celms[:-2] + "žņ", I_MIJA, "zn -> žņ")
        elif celms.endswith("ln"):
            yield Variants(celms[:-2] + "ļņ", I_MIJA, "ln -> ļņ")
        elif celms.endswith("nn"):
            yield Variants(celms[:-2] + "ņņ", I_MIJA, "nn -> ņņ")
        else:
            yield Variants(celms[:-1] + "ņ", I_MIJA, "n -> ņ")
    elif celms.endswith(("p", "b", "m", "v", "f")):
        yield Variants(celms + "j", I_MIJA, "p->pj (u.c.)")
    elif not celms.endswith(("p", "b", "m", "v", "t", "d", "c", "z", "s", "n", "l", "f")):
        yield Variants(celms)


def _inf_2(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """3rd-conjugation present that drops the stem's last char."""
    if celms.endswith(("ī", "inā", "sargā")):
        yield Variants(celms[:-1], "Garā", "ā")
    else:
        yield Variants(celms[:-1])


def _inf_3(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """Adjective: positive + comparative -āk-, optional vis- superlative."""
    yield Variants(celms, I_DEGREE, V_POSITIVE)
    if not celms.endswith("āk"):
        yield Variants(celms + "āk", I_DEGREE, V_COMPARATIVE)
        if add_superlative:
            yield Variants("vis" + celms + "āk", I_DEGREE, V_SUPERLATIVE)


def _inf_6(celms: str, third_stem: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """1st-conjugation future — uses third_stem (past) ending to choose suffix."""
    if celms.endswith("s"):
        if third_stem.endswith("d"):
            yield Variants(celms[:-1] + "dī")
        elif third_stem.endswith("t"):
            yield Variants(celms[:-1] + "tī")
        elif third_stem.endswith("s"):
            yield Variants(celms[:-1] + "sī")
        else:
            yield Variants(celms)
    elif celms.endswith(("z", "š")):
        yield Variants(celms + "ī")
    else:
        yield Variants(celms)


def _inf_7_or_23(
    celms: str, third_stem: str, mija: int
) -> Iterator[Variants]:
    """1st-conjugation 2nd-person present (mija=7 short, mija=23 long-ending like -iet)."""
    if celms.endswith("š") and third_stem.endswith("s"):
        yield Variants(celms[:-1] + "s")
    elif celms.endswith("š") and third_stem.endswith("t"):
        yield Variants(celms[:-1] + "t")
    elif (
        (celms.endswith("od") and not celms.endswith("dod"))
        or celms.endswith(("ūd", "op", "ūp", "ot", "ūt", "īt", "iet", "st"))
    ):
        if mija == 7:
            yield Variants(celms + "i")
        else:
            yield Variants(celms)
    elif celms.endswith("ļ"):
        yield Variants(celms[:-1] + "l")
    elif celms.endswith(("mj", "bj", "pj")):
        yield Variants(celms[:-1])
    elif celms.endswith("k"):
        yield Variants(celms[:-1] + "c")
    elif celms.endswith("g"):
        yield Variants(celms[:-1] + "dz")
    elif celms.endswith("ž"):
        # skaužu -> skaud, laužu -> lauz; falls back to past-tense stem
        yield Variants(third_stem)
    else:
        yield Variants(celms)


# ----- LV cases 8-38 (generation) -----------------------------------------


def _inf_8(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """-ams/-āms 3rd-conj no-mija + we/you forms."""
    if celms.endswith(("inā", "sargā")):
        yield Variants(celms, "Garā", "ā")
    elif celms.endswith("ī"):
        yield Variants(celms[:-1] + "ā", "Garā", "ā")
    elif celms.endswith("ē"):
        yield Variants(celms[:-1] + "a")
    elif celms.endswith("ā"):
        yield Variants(celms[:-1] + "a")
    else:
        yield Variants(celms)


def _inf_9(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """3rd-conj 3rd-person present, no mija."""
    if celms.endswith("dā"):
        yield Variants(celms[:-1])  # dzied, raud
    elif celms.endswith(("ā", "ī")):
        yield Variants(celms[:-1] + "a")
    else:
        yield Variants(celms[:-1])


def _inf_10(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """Adjective -āk-/vis-, -i adverb form."""
    yield Variants(celms, I_DEGREE, V_POSITIVE)
    yield Variants(celms + "āk", I_DEGREE, V_COMPARATIVE)
    if add_superlative:
        yield Variants("vis" + celms + "āk", I_DEGREE, V_SUPERLATIVE)


def _inf_11(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """-uša forms."""
    if celms.endswith("c"):
        yield Variants(celms[:-1] + "k")
    elif celms.endswith("dz"):
        yield Variants(celms[:-2] + "g")
    else:
        yield Variants(celms)


def _inf_13(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """Adjective -āk- with š→s in nominative (zaļš → zaļāks)."""
    yield Variants(celms + "āk", I_DEGREE, V_COMPARATIVE)
    if add_superlative:
        yield Variants("vis" + celms + "āk", I_DEGREE, V_SUPERLATIVE)


def _inf_14(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """1st-conjugation -is form."""
    if celms.endswith("k"):
        yield Variants(celms[:-1] + "c")
    elif celms.endswith("g"):
        yield Variants(celms[:-1] + "dz")
    else:
        yield Variants(celms)


def _inf_15(celms: str, third_stem: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """pūst → pūzdams, only when third_stem ends in t/d."""
    if celms.endswith("s") and third_stem.endswith(("t", "d")):
        yield Variants(celms[:-1] + "z")
    else:
        yield Variants(celms)


def _inf_16(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """1st-conjugation -šana derivation."""
    if celms.endswith(("s", "z")):
        yield Variants(celms[:-1])  # nest -> nešana
    else:
        yield Variants(celms)


def _inf_17(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """Short feminine vocative — 'kristīnīt!', 'margriet!'."""
    if syllables(celms) >= 2 and not celms.endswith(("kāj", "māj")):
        yield Variants(celms)


def _inf_20(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """3rd-conjugation present mija for 1st-person present, -ot, debitive."""
    if celms.endswith("gulē"):
        yield Variants(celms[:-2] + "ļ")  # gulēt -> guļu
    elif celms.endswith("cī"):
        yield Variants(celms[:-2] + "k", "Garā", "ā")  # sacīt
    elif celms.endswith("cē"):
        yield Variants(celms[:-2] + "k")  # mācēt -> māku
    elif celms.endswith("dē"):
        yield Variants(celms[:-2] + "ž")  # sēdēt -> sēžu
    elif celms.endswith(("dzē", "dzī")):
        yield Variants(celms[:-3] + "g")  # vajadzēt -> vajag, slodzīt -> slogu


def _inf_21(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """-is/-ušais comparative and superlative."""
    yield Variants(celms, I_DEGREE, V_COMPARATIVE)
    if add_superlative:
        yield Variants("vis" + celms, I_DEGREE, V_SUPERLATIVE)


def _inf_22(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """jaundzimušais → jaundzimusī."""
    if celms.endswith("uš"):
        yield Variants(celms[:-2] + "us")


def _inf_24(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """Like case 2 but for comparative/superlative."""
    yield Variants(celms[:-1], I_DEGREE, V_COMPARATIVE)
    if add_superlative:
        yield Variants("vis" + celms[:-1], I_DEGREE, V_SUPERLATIVE)


def _inf_25(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """Like case 8 but for comparative/superlative — for -amāks forms."""
    if celms.endswith(("inā", "sargā")):
        yield Variants(celms, I_DEGREE, V_COMPARATIVE)
    elif celms.endswith("ī"):
        yield Variants(celms[:-1] + "ā", I_DEGREE, V_COMPARATIVE)
    elif celms.endswith("ē"):
        yield Variants(celms[:-1] + "a", I_DEGREE, V_COMPARATIVE)
    elif celms.endswith("ā"):
        yield Variants(celms[:-1] + "a", I_DEGREE, V_COMPARATIVE)
    else:
        yield Variants(celms, I_DEGREE, V_COMPARATIVE)
    if add_superlative:
        if celms.endswith(("inā", "sargā")):
            yield Variants("vis" + celms, I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("ī"):
            yield Variants("vis" + celms[:-1] + "ā", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("ē"):
            yield Variants("vis" + celms[:-1] + "a", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("ā"):
            yield Variants("vis" + celms[:-1] + "a", I_DEGREE, V_SUPERLATIVE)
        else:
            yield Variants("vis" + celms, I_DEGREE, V_SUPERLATIVE)


def _inf_26(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """3rd-conjugation mija — 2nd-person present, imperative."""
    if celms.endswith("lē"):
        yield Variants(celms[:-1])  # gulēt -> guli
    elif celms.endswith("cī"):
        yield Variants(celms[:-2] + "k", "Garā", "ā")  # sacīt -> saki
    elif celms.endswith("tecē"):
        yield Variants(celms[:-2] + "c")  # tecēt -> teci
    elif celms.endswith("cē"):
        yield Variants(celms[:-2] + "k")  # mācēt -> māki
    elif celms.endswith(("dzē", "dzī")):
        yield Variants(celms[:-3] + "g")  # vajadzēt -> vajag, slodzīt -> slogi
    else:
        yield Variants(celms[:-1])  # sēdē-ties -> sēd-ies


def _inf_27(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """-ams/-āms 3rd-conjugation mija + we/you forms."""
    if celms.endswith("cī"):
        yield Variants(celms[:-2] + "kā", "Garā", "ā")  # sacīt -> sakām
    elif celms.endswith("dzī"):
        yield Variants(celms[:-3] + "gā")  # slodzīt -> slogām
    elif celms.endswith("cē"):
        yield Variants(celms[:-2] + "ka")  # mācēt -> mākam
    elif celms.endswith("gulē"):
        yield Variants(celms[:-2] + "ļa")  # gulēt -> guļam
    elif celms.endswith("dē"):
        yield Variants(celms[:-2] + "ža")  # sēdēt -> sēžam
    elif celms.endswith("dzē"):
        yield Variants(celms[:-3] + "ga")  # vajadzēt -> vajagam


def _inf_30(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """3rd-conjugation 3rd-person present with mija."""
    if celms.endswith("cī"):
        yield Variants(celms[:-2] + "ka")
    elif celms.endswith("dzī"):
        yield Variants(celms[:-3] + "ga")  # slodzīt -> sloga
    elif celms.endswith("cē"):
        yield Variants(celms[:-2] + "k")  # mācēt -> māk
    elif celms.endswith("dē"):
        yield Variants(celms[:-2] + "ž")  # sēdēt -> sēž
    elif celms.endswith("dzē"):
        yield Variants(celms[:-3] + "g")  # vajadzēt -> vajag
    elif celms.endswith("lē"):
        yield Variants(celms[:-2] + "ļ")  # gulēt -> guļ


def _inf_32(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """Like case 20 but with comparative/superlative."""
    if celms.endswith(("cī", "cē")):
        yield Variants(celms[:-2] + "k", I_DEGREE, V_COMPARATIVE)
    elif celms.endswith(("dzī", "dzē")):
        yield Variants(celms[:-3] + "g", I_DEGREE, V_COMPARATIVE)
    elif celms.endswith("dē"):
        yield Variants(celms[:-2] + "ž", I_DEGREE, V_COMPARATIVE)
    elif celms.endswith("lē"):
        yield Variants(celms[:-2] + "ļ", I_DEGREE, V_COMPARATIVE)
    else:
        yield Variants(celms[:-1], I_DEGREE, V_COMPARATIVE)
    if add_superlative:
        if celms.endswith(("cī", "cē")):
            yield Variants("vis" + celms[:-2] + "k", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("vajadzē"):
            yield Variants("vis" + celms[:-3] + "g", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith(("dzī", "dzē")):
            yield Variants("vis" + celms[:-3] + "g", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("dē"):
            yield Variants("vis" + celms[:-2] + "ž", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("gulē"):
            yield Variants("vis" + celms[:-2] + "ļ")  # NB: Java forgot the degree label here
        else:
            yield Variants("vis" + celms[:-1], I_DEGREE, V_SUPERLATIVE)


def _inf_33(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """Like case 27 but with comparative/superlative — -amāks forms."""
    if celms.endswith("cī"):
        yield Variants(celms[:-2] + "kā", I_DEGREE, V_COMPARATIVE)
    elif celms.endswith("dzī"):
        yield Variants(celms[:-3] + "gā", I_DEGREE, V_COMPARATIVE)
    elif celms.endswith("cē"):
        yield Variants(celms[:-2] + "ka", I_DEGREE, V_COMPARATIVE)
    elif celms.endswith("lē"):
        yield Variants(celms[:-2] + "ļa", I_DEGREE, V_COMPARATIVE)
    elif celms.endswith("dē"):
        yield Variants(celms[:-2] + "ža", I_DEGREE, V_COMPARATIVE)
    elif celms.endswith("dzē"):
        yield Variants(celms[:-3] + "ga", I_DEGREE, V_COMPARATIVE)
    if add_superlative:
        if celms.endswith("cī"):
            yield Variants("vis" + celms[:-2] + "kā", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("dzī"):
            yield Variants("vis" + celms[:-3] + "gā", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("cē"):
            yield Variants("vis" + celms[:-2] + "ka", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("lē"):
            yield Variants("vis" + celms[:-2] + "ļa", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("dē"):
            yield Variants("vis" + celms[:-2] + "ža", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("dzē"):
            yield Variants("vis" + celms[:-3] + "ga", I_DEGREE, V_SUPERLATIVE)


def _inf_34(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """Adjective -āk-/vis- with -ajam endings."""
    if celms.endswith("ēj"):  # pēdēj-ais -> pēdē-jam
        yield Variants(celms[:-1], I_DEGREE, V_POSITIVE)
    else:  # zaļ-š -> zaļa-jam
        yield Variants(celms + "a", I_DEGREE, V_POSITIVE)
    yield Variants(celms + "āka", I_DEGREE, V_COMPARATIVE)
    if add_superlative:
        yield Variants("vis" + celms + "āka", I_DEGREE, V_SUPERLATIVE)


def _inf_35(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """Substantivized 'adjective' -ajam endings."""
    if celms.endswith("ēj"):
        yield Variants(celms[:-1], I_DEGREE, V_POSITIVE)
    else:
        yield Variants(celms + "a", I_DEGREE, V_POSITIVE)


def _inf_36(celms: str, third_stem: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """'iet' special case — 3rd-person stem 'iet' when third_stem ends in 'gāj'."""
    if celms.endswith("ej") and third_stem.endswith("gāj"):
        yield Variants(celms[:-2] + "iet")
    else:
        yield Variants(celms)


def _inf_38(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """Adverbs with degree gradation."""
    yield Variants(celms, I_DEGREE, V_POSITIVE)
    base = celms[:-1] if celms.endswith(("i", "u")) else celms
    yield Variants(base + "āk", I_DEGREE, V_COMPARATIVE)
    if add_superlative:
        yield Variants("vis" + base + "āk", I_DEGREE, V_SUPERLATIVE)


# ----- LTG cases 99-127 (generation) --------------------------------------


def _inf_99(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG burtu mija half (case 99)."""
    yield Variants(_ltg_burtu_mija(celms))


def _inf_100(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG burtu mija (case 100)."""
    yield Variants(_ltg_burtu_mija(celms))


def _inf_101(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG noun consonant mija for ordinary endings."""
    if celms.endswith("kst"):
        yield Variants(celms[:-3] + "kš")
    elif celms.endswith("sl"):
        yield Variants(celms[:-2] + "šļ")
    elif celms.endswith("zl"):
        yield Variants(celms[:-2] + "žļ")
    elif celms.endswith("sm"):
        yield Variants(celms[:-2] + "šm")
    elif celms.endswith("sn"):
        yield Variants(celms[:-2] + "šņ")
    elif celms.endswith("zn"):
        yield Variants(celms[:-2] + "žņ")
    elif celms.endswith("ll"):
        yield Variants(celms[:-2] + "ļļ")
    elif celms.endswith("nn"):
        yield Variants(celms[:-2] + "ņņ")
    elif celms.endswith("c"):
        yield Variants(celms[:-1] + "č")
    elif celms.endswith("d"):
        yield Variants(celms[:-1] + "ž")
    elif celms.endswith("s"):
        yield Variants(celms[:-1] + "š")
    elif celms.endswith("t"):
        yield Variants(celms[:-1] + "š")
    elif celms.endswith("z"):
        yield Variants(celms[:-1] + "ž")
    elif celms.endswith("k"):
        yield Variants(celms[:-1] + "ķ")
    elif celms.endswith("l"):
        yield Variants(celms[:-1] + "ļ")
    elif celms.endswith("n"):
        yield Variants(celms[:-1] + "ņ")
    else:
        yield Variants(celms)


def _inf_102(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG noun consonant softening for e/i/ē/ī/ie endings."""
    if celms.endswith("kst"):
        yield Variants(celms[:-3] + "kš")
    elif celms.endswith(("šļ", "sl")):
        yield Variants(celms[:-2] + "šl")
    elif celms.endswith(("žļ", "zl")):
        yield Variants(celms[:-2] + "žl")
    elif celms.endswith(("šm", "sm")):
        yield Variants(celms[:-2] + "šm")
    elif celms.endswith(("šņ", "sn")):
        yield Variants(celms[:-2] + "šn")
    elif celms.endswith(("žņ", "zn")):
        yield Variants(celms[:-2] + "žn")
    elif celms.endswith("ļļ"):
        yield Variants(celms[:-2] + "ll")
    elif celms.endswith("ņņ"):
        yield Variants(celms[:-2] + "nn")
    elif celms.endswith("c"):
        yield Variants(celms[:-1] + "č")
    elif celms.endswith("s"):
        yield Variants(celms[:-1] + "š")
    elif celms.endswith("t"):
        yield Variants(celms[:-1] + "š")
    elif celms.endswith("z"):
        yield Variants(celms[:-1] + "ž")
    elif celms.endswith("d"):
        yield Variants(celms[:-1] + "ž")
    elif celms.endswith("ļ"):
        yield Variants(celms[:-1] + "l")
    elif celms.endswith("ņ"):
        yield Variants(celms[:-1] + "n")
    elif celms.endswith("ķ"):
        yield Variants(celms[:-1] + "k")
    elif celms.endswith("ģ"):
        yield Variants(celms[:-1] + "g")
    else:
        yield Variants(celms)


def _ltg_emit_super(base: str, add_superlative: bool, degree_label: str) -> Iterator[Variants]:
    """Helper for LTG superlatives: emit comparative + (if requested) `vys-` and `vysu-` superlatives."""
    yield Variants(base, attributes=_ltg_degree_flags(degree_label))
    # No superlative variant emitted by this helper — caller decides.


def _inf_103(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG adjective gradation (-uok-, vys-/vysu-)."""
    yield Variants(celms, attributes=_ltg_degree_flags(V_POSITIVE))
    if not celms.endswith("uok"):
        yield Variants(celms + "uok", attributes=_ltg_degree_flags(V_COMPARATIVE))
        if add_superlative:
            yield Variants("vys" + celms + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))
            yield Variants("vysu" + celms + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _inf_104(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG adjective gradation + burtu mija on positive."""
    yield Variants(_ltg_burtu_mija(celms), attributes=_ltg_degree_flags(V_POSITIVE))
    if not celms.endswith("uok"):
        yield Variants(celms + "uok", attributes=_ltg_degree_flags(V_COMPARATIVE))
        if add_superlative:
            yield Variants("vys" + celms + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))
            yield Variants("vysu" + celms + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _inf_105(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG adjective -uoka with -ajam endings."""
    if celms.endswith(("ēj", "ej")):
        yield Variants(celms[:-1], attributes=_ltg_degree_flags(V_POSITIVE))
    else:
        yield Variants(celms + "a", attributes=_ltg_degree_flags(V_POSITIVE))
    yield Variants(celms + "uoka", attributes=_ltg_degree_flags(V_COMPARATIVE))
    if add_superlative:
        yield Variants("vys" + celms + "uoka", attributes=_ltg_degree_flags(V_SUPERLATIVE))
        yield Variants("vysu" + celms + "uoka", attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _inf_106(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG adverb gradation (no positive form)."""
    if not celms.endswith("uok"):
        yield Variants(celms + "uok", attributes=_ltg_degree_flags(V_COMPARATIVE))
        if add_superlative:
            yield Variants("vys" + celms + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))
            yield Variants("vysu" + celms + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _inf_107(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG burtu mija inverse (lemma ending is -e/-i/-ī/-ē/-ie)."""
    yield Variants(_ltg_burtu_mija_atpakal_viennoz(celms))


def _inf_108(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """107 + 106 — for slapnis-style words."""
    if not celms.endswith("uok"):
        base = _ltg_burtu_mija_atpakal_viennoz(celms)
        yield Variants(base + "uok", attributes=_ltg_degree_flags(V_COMPARATIVE))
        if add_superlative:
            yield Variants("vys" + base + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))
            yield Variants("vysu" + base + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _inf_109(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG adverb gradation, no burtu mija."""
    yield Variants(celms, attributes=_ltg_degree_flags(V_POSITIVE))
    if celms.endswith("ai"):
        celms = celms[:-2]
    elif celms.endswith(("i", "a")):
        celms = celms[:-1]
    yield Variants(celms + "uok", attributes=_ltg_degree_flags(V_COMPARATIVE))
    if add_superlative:
        yield Variants("vys" + celms + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))
        yield Variants("vysu" + celms + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _inf_110(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple present mija."""
    if celms.endswith("uo"):
        yield Variants(celms[:-2] + "o")
    elif celms.endswith("ei"):
        yield Variants(celms[:-2] + "e")
    elif celms.endswith("ē"):
        yield Variants(celms[:-1] + "e")


def _inf_111(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple-past 1st/2nd person singular."""
    if celms.endswith("uo"):
        yield Variants(celms + "j")
        yield Variants(celms[:-2] + "ov")
    elif celms.endswith("ei"):
        yield Variants(celms[:-2] + "ej")
    elif celms.endswith("ē"):
        yield Variants(celms[:-1] + "iej")


def _inf_112(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple-past plural and 3rd person."""
    if celms.endswith("uo"):
        yield Variants(celms + "j")
        yield Variants(celms[:-2] + "ov")
    elif celms.endswith("ei"):
        yield Variants(celms[:-2] + "ej")
    elif celms.endswith("ē"):
        yield Variants(celms + "j")


def _inf_113(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple-future 1st/2nd person singular."""
    if celms.endswith("ē"):
        yield Variants(celms[:-1] + "ie")
    elif celms.endswith(("ei", "uo")):
        yield Variants(celms)


def _inf_114(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 2nd-conj subjunctive, supinum, passive past participle, -dams participle."""
    if celms.endswith("ē"):
        yield Variants(celms[:-1] + "ā")
    elif celms.endswith(("ei", "uo")):
        yield Variants(celms)


def _ltg_super_emit(stem: str, add_superlative: bool) -> Iterator[Variants]:
    """Emit comparative + optional vys-/vysu- superlatives. Used by cases 115-127."""
    yield Variants(stem, attributes=_ltg_degree_flags(V_COMPARATIVE))
    if add_superlative:
        yield Variants("vys" + stem, attributes=_ltg_degree_flags(V_SUPERLATIVE))
        yield Variants("vysu" + stem, attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _inf_115(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 2nd-conj participle superlative (121.) + present mija (110.)."""
    if celms.endswith("uo"):
        yield from _ltg_super_emit(celms[:-2] + "o", add_superlative)
    elif celms.endswith("ei"):
        yield from _ltg_super_emit(celms[:-2] + "e", add_superlative)
    elif celms.endswith("ē"):
        yield from _ltg_super_emit(celms[:-1] + "e", add_superlative)


def _inf_116(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 2nd-conj participle superlative + subjunctive/supinum mija (114.) for -ts."""
    if celms.endswith("ē"):
        yield from _ltg_super_emit(celms[:-1] + "ā", add_superlative)
    elif celms.endswith(("ei", "uo")):
        yield from _ltg_super_emit(celms, add_superlative)


def _inf_117(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 2nd-conj past mija for -s, -use participle (simplified 111.)."""
    if celms.endswith("uo"):
        yield Variants(celms)
    elif celms.endswith("ei"):
        yield Variants(celms[:-2] + "e")
    elif celms.endswith("ē"):
        yield Variants(celms[:-1] + "ie")


def _inf_118(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 2nd-conj participle superlative + past mija for -s, -use (117.)."""
    if celms.endswith("ei"):
        yield from _ltg_super_emit(celms[:-2] + "e", add_superlative)
    elif celms.endswith("ē"):
        yield from _ltg_super_emit(celms[:-1] + "ie", add_superlative)
    elif celms.endswith("uo"):
        yield from _ltg_super_emit(celms, add_superlative)


def _inf_119(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -eit, present and past."""
    if celms.endswith("ei"):
        yield Variants(celms[:-2])


def _inf_120(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -eit + participle superlative + present/past mija (119.)."""
    if celms.endswith("ei"):
        yield from _ltg_super_emit(celms[:-2], add_superlative)


def _inf_121(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 3rd-conj participle superlative without mija."""
    yield from _ltg_super_emit(celms, add_superlative)


def _inf_122(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -eit, present with consonant mija."""
    if celms.endswith("ļdei"):
        yield Variants(celms[:-4] + "ld")
    elif celms.endswith("ņdei"):
        yield Variants(celms[:-4] + "nd")
    elif celms.endswith("dzei"):
        yield Variants(celms[:-4] + "g")
    elif celms.endswith("cei"):
        yield Variants(celms[:-3] + "k")
    elif celms.endswith("lei"):
        yield Variants(celms[:-3] + "ļ")
    elif celms.endswith("nei"):
        yield Variants(celms[:-3] + "ņ")


def _inf_123(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -eit consonant mija + participle superlative + present mija (122.)."""
    if celms.endswith("ļdei"):
        base = celms[:-4] + "ld"
    elif celms.endswith("ņdei"):
        base = celms[:-4] + "nd"
    elif celms.endswith("dzei"):
        base = celms[:-4] + "g"
    elif celms.endswith("cei"):
        base = celms[:-3] + "k"
    elif celms.endswith("lei"):
        base = celms[:-3] + "ļ"
    elif celms.endswith("nei"):
        base = celms[:-3] + "ņ"
    else:
        return
    yield from _ltg_super_emit(base, add_superlative)


def _inf_124(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -ēt, present and past, no consonant or letter mija."""
    if celms.endswith("ē"):
        yield Variants(celms[:-1])


def _inf_125(celms: str, _third: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -ēt, present without consonant mija but with inverse letter mija."""
    if celms.endswith("ē"):
        yield Variants(_ltg_burtu_mija_atpakal_viennoz(celms[:-1]))


def _inf_126(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -ēt no consonant/letter mija + participle superlative + present/past mija (119.)."""
    if celms.endswith("ē"):
        yield from _ltg_super_emit(celms[:-1], add_superlative)


def _inf_127(celms: str, _third: str, add_superlative: bool, _proper: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -ēt with inverse letter mija + participle superlative + present/past mija (119.)."""
    if celms.endswith("ē"):
        yield from _ltg_super_emit(_ltg_burtu_mija_atpakal_viennoz(celms[:-1]), add_superlative)


def _inf_7(celms: str, third_stem: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    return _inf_7_or_23(celms, third_stem, mija=7)


def _inf_23(celms: str, third_stem: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    return _inf_7_or_23(celms, third_stem, mija=23)


_HANDLERS_INFLECTION: dict[
    int, Callable[[str, str, bool, bool], Iterator[Variants]]
] = {
    0: _inf_0, 1: _inf_1, 2: _inf_2, 3: _inf_3, 6: _inf_6, 7: _inf_7,
    8: _inf_8, 9: _inf_9, 10: _inf_10, 11: _inf_11, 13: _inf_13, 14: _inf_14,
    15: _inf_15, 16: _inf_16, 17: _inf_17, 20: _inf_20, 21: _inf_21, 22: _inf_22,
    23: _inf_23, 24: _inf_24, 25: _inf_25, 26: _inf_26, 27: _inf_27, 30: _inf_30,
    32: _inf_32, 33: _inf_33, 34: _inf_34, 35: _inf_35, 36: _inf_36, 38: _inf_38,
    # ----- Latgalian -----
    99: _inf_99, 100: _inf_100, 101: _inf_101, 102: _inf_102, 103: _inf_103,
    104: _inf_104, 105: _inf_105, 106: _inf_106, 107: _inf_107, 108: _inf_108,
    109: _inf_109, 110: _inf_110, 111: _inf_111, 112: _inf_112, 113: _inf_113,
    114: _inf_114, 115: _inf_115, 116: _inf_116, 117: _inf_117, 118: _inf_118,
    119: _inf_119, 120: _inf_120, 121: _inf_121, 122: _inf_122, 123: _inf_123,
    124: _inf_124, 125: _inf_125, 126: _inf_126, 127: _inf_127,
}


def mija_for_inflection(
    stem: str,
    stem_change: int,
    third_stem: str = "",
    add_superlative: bool = False,
    proper_name: bool = False,
) -> list[Variants]:
    """Given a base stem and target ending's stem-change ID, return all surface
    stems the ending can attach to.

    Port of `Mijas.MijasLocīšanai`. Cases beyond 0-7+23 are pending — will raise
    `NotImplementedError` for un-ported cases.
    """
    if not stem.strip():
        return []

    redirect = _resolve_redirect_inflection(stem, stem_change)
    if redirect is not None:
        celms, mija = redirect
    else:
        celms, mija = stem, stem_change

    handler = _HANDLERS_INFLECTION.get(mija)
    if handler is None:
        raise NotImplementedError(
            f"mija_for_inflection: case {mija} not yet ported (was stem_change={stem_change})"
        )
    return list(handler(celms, third_stem, add_superlative, proper_name))


# Cases that always pass verification (asymmetric by design):
#   18 — vocative "silvij!" recognized but not generated
#   20 — alternative forms: "guļošs" and "gulošs"
#   34/35 — "pēdējajam", "zaļoksnējajam" recognized but not generated
_ALWAYS_VERIFY: frozenset[int] = frozenset({18, 20, 34, 35})

# Cases where verification failure is fatal (return False rather than warn-and-pass):
_STRICT_VERIFY: frozenset[int] = frozenset({1, 2, 5, 6, 7, 8, 9, 14, 15, 17, 23, 26, 36, 37})


def verify_back_inflection(
    variant: Variants,
    stem: str,
    stem_change: int,
    third_stem: str = "",
    proper_name: bool = False,
) -> bool:
    """Verify that re-inflecting an analysis variant reproduces the original stem.

    Direct port of `Mijas.atpakaļlocīšanasVerifikācija`. The analyzer over-
    generates candidates, so this re-runs the inflector on each candidate
    and discards those that don't round-trip. Some asymmetric cases
    (`_ALWAYS_VERIFY`) are exempt; some `_STRICT_VERIFY` cases fail hard.
    """
    if stem_change in _ALWAYS_VERIFY:
        return True

    # Case 6: trim a trailing 'ī' from the past stem before re-inflecting.
    if stem_change == 6 and third_stem.endswith("ī"):
        third_stem = third_stem[:-1]

    is_superlative = variant.is_matching_strong(I_DEGREE, V_SUPERLATIVE)
    candidates = mija_for_inflection(
        variant.celms, stem_change, third_stem, is_superlative, proper_name
    )

    found = any(c.celms.casefold() == stem.casefold() for c in candidates)

    if not found and stem_change in _STRICT_VERIFY:
        # Case 7 exception: "dodi" is recognized but not generated.
        if stem_change == 7 and variant.celms.endswith("dod"):
            return True
        if proper_name:
            # During analysis, properName can be misset (uppercase due to
            # sentence-initial position); retry without the flag.
            return verify_back_inflection(variant, stem, stem_change, third_stem, False)
        return False

    return True
