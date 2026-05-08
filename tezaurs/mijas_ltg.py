"""Latgalian (LTG) mijas — the Latgalian-specific stem alternations,
both analysis (`_case_99..127`) and generation (`_inf_99..127`) directions.

Lives in its own module to keep the LV file (`mijas.py`) focused. Shares
the `SuffixRule` DSL primitives via `mijas_dsl`. The dispatcher in
`mijas.py` imports `LTG_HANDLERS_VARIANTS` / `LTG_HANDLERS_INFLECTION`
and merges them with the LV handlers.

Compression notes:
  * Cases 103/104/106/108 share a `vys-/vysu- + -uok` analysis kernel.
  * Cases 122/123 share a 6-row consonant→consonant suffix table.
  * Cases 110/115 and 117/118 share consonant pairs distinguished only by
    whether degree-wrapping is applied.
  * `_ltg_super_emit` covers the "comparative + optional vys-/vysu-
    superlatives" emission that appears in 12 inflection-direction cases.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator

from tezaurs.attributes import AttributeValues
from tezaurs.mijas_dsl import (
    I_DEGREE,
    I_MIJA,
    I_NORMATIVE,
    SuffixRule,
    V_COMPARATIVE,
    V_POSITIVE,
    V_SUPERLATIVE,
    V_UNDESIRABLE,
    _apply_first,
    _strip_vys,
)
from tezaurs.variants import Variants


# ---------------------------------------------------------------------------
# Latgalian vowel and consonant alternations.
# ---------------------------------------------------------------------------

_LTG_FORWARD_RE = re.compile(
    r"(.*?)(ai|ei|ui|oi|ie|[aāeēiīouūy])"
    r"([bcčdfgģhjkķlļmnņprŗsštvzž]+[aāeēiīyoōuū]*)$"
)
_LTG_BACKWARD_RE = re.compile(
    r"(.*?)(uo|[aāeēiīouūy]|)"
    r"([bcčdfgģhjkķlļmnņprŗsštvzž]+[aāeēiīyoōuū]*)$"
)

_LTG_FWD_MAP = {"a": "o", "e": "a", "ē": "ā", "i": "y"}
_LTG_BWD_MAP = {"a": "e", "ā": "ē", "y": "i", "o": "a"}


def _ltg_patskanu_mija_locisanai(celms: str) -> str:
    """Forward LTG vowel alternation: a→o, e→a, ē→ā, i→y on the syllable nucleus."""
    m = _LTG_FORWARD_RE.match(celms)
    if not m:
        return celms
    pre, vowel, post = m.groups()
    new = _LTG_FWD_MAP.get(vowel)
    return f"{pre}{new}{post}" if new else celms


def _ltg_patskanu_mija_atpakal_locisanai(celms: str) -> str:
    """Reverse LTG vowel alternation: a→e, ā→ē, y→i, o→a (no `uo`)."""
    m = _LTG_BACKWARD_RE.match(celms)
    if not m:
        return celms
    pre, vowel, post = m.groups()
    new = _LTG_BWD_MAP.get(vowel)
    return f"{pre}{new}{post}" if new else celms


# Forward letter mija (soft → hard before -e/-i/-ī/-ē/-ie).
_LTG_BURTU_FWD = (
    SuffixRule("ļļ", "ll"),
    SuffixRule("ņņ", "nn"),
    SuffixRule("ļ", "l"),
    SuffixRule("ņ", "n"),
    SuffixRule("ķ", "k"),
    SuffixRule("ģ", "g"),
)

# Reverse letter mija (hard → soft, unambiguous).
_LTG_BURTU_REV = (
    SuffixRule("ll", "ļļ"),
    SuffixRule("nn", "ņņ"),
    SuffixRule("l", "ļ"),
    SuffixRule("n", "ņ"),
    SuffixRule("k", "ķ"),
    SuffixRule("g", "ģ"),
)


def _ltg_burtu_mija(celms: str) -> str:
    for r in _LTG_BURTU_FWD:
        if celms.endswith(r.match):
            return celms[:-len(r.match)] + r.replace
    return celms


def _ltg_burtu_mija_atpakal_viennoz(celms: str) -> str:
    for r in _LTG_BURTU_REV:
        if celms.endswith(r.match):
            return celms[:-len(r.match)] + r.replace
    return celms


def _ltg_degree_flags(degree: str) -> AttributeValues:
    """LTG superlatives via `vys`/`vysu` are grammatically discouraged — we
    tag those `Nevēlams` in addition to the degree itself."""
    av = AttributeValues()
    av.add(I_DEGREE, degree)
    if degree == V_SUPERLATIVE:
        av.add(I_NORMATIVE, V_UNDESIRABLE)
    return av


def _ltg_super_emit(stem: str, add_superlative: bool) -> Iterator[Variants]:
    """Emit comparative + optional vys-/vysu- superlatives. Used by 12
    inflection-direction cases (115-127)."""
    yield Variants(stem, attributes=_ltg_degree_flags(V_COMPARATIVE))
    if add_superlative:
        yield Variants("vys" + stem, attributes=_ltg_degree_flags(V_SUPERLATIVE))
        yield Variants("vysu" + stem, attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _ltg_emit_uok_with_degree(celms: str, transform: Callable[[str], str] | None = None) -> Iterator[Variants]:
    """Cases 103/104/106/108 share the `vys-/vysu- prefix + -uok suffix +
    degree-tagged emit` kernel; the only knob is whether a transform (e.g.
    `_ltg_burtu_mija`) is applied to the stem first."""
    if not (celms.endswith("uok") and len(celms) > 3):
        return
    stem, degree = _strip_vys(celms)
    base = stem[:-3]
    if transform is not None:
        base = transform(base)
    yield Variants(base, attributes=_ltg_degree_flags(degree))


# ---------------------------------------------------------------------------
# Shared LTG rule tables.
# ---------------------------------------------------------------------------

# Cases 122 (no degree) and 123 (with degree) — 3rd-conj -eit consonant mija.
_LTG_3RD_EIT_MIJA = (
    SuffixRule("ld", "ļdei",  "ļdei -> ld"),
    SuffixRule("nd", "ņdei",  "ņdei -> nd"),
    SuffixRule("g",  "dzei",  "dzei -> g"),
    SuffixRule("k",  "cei",   "cei -> k"),
    SuffixRule("ļ",  "lei",   "lei -> ļ"),
    SuffixRule("ņ",  "nei",   "nei -> ņ"),
)

# Cases 122/123 inflection direction (reverse of above).
_LTG_3RD_EIT_MIJA_REV = (
    SuffixRule("ļdei", "ld"),
    SuffixRule("ņdei", "nd"),
    SuffixRule("dzei", "g"),
    SuffixRule("cei",  "k"),
    SuffixRule("lei",  "ļ"),
    SuffixRule("nei",  "ņ"),
)


# ===========================================================================
# Analysis direction (`_case_99..127`).
# ===========================================================================


def _case_99(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Half of LTG burtu mija — only for paradigms whose no-mija stem ends soft."""
    yield Variants(_ltg_burtu_mija_atpakal_viennoz(celms), I_MIJA, "ļņķģ -> lnkg")


def _case_100(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG burtu mija — before -e/-i/-ī/-ē/-ie, ļ/ņ/ķ/ģ become l/n/k/g."""
    softened = _ltg_burtu_mija_atpakal_viennoz(celms)
    yield Variants(softened, I_MIJA, "lnkg -> lļnņkķgģ")
    if softened != celms:
        yield Variants(celms, I_MIJA, "lnkg -> lļnņkķgģ")


def _case_101(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG noun consonant mija (excluding -i/-e/-ī/-ē/-ie/-ei endings)."""
    if celms.endswith("kš"):
        yield Variants(celms[:-2] + "kst", I_MIJA, "kst -> kš")
    elif celms.endswith("šļ"):
        yield Variants(celms[:-2] + "sl", I_MIJA, "sl -> šļ")
    elif celms.endswith("žļ"):
        yield Variants(celms[:-2] + "zl", I_MIJA, "zl -> žļ")
    elif celms.endswith("šm"):
        yield Variants(celms[:-2] + "sm", I_MIJA, "sm -> šm")
    elif celms.endswith("šņ"):
        yield Variants(celms[:-2] + "sn", I_MIJA, "sn -> šņ")
    elif celms.endswith("žņ"):
        yield Variants(celms[:-2] + "zn", I_MIJA, "zn -> žņ")
    elif celms.endswith("ļļ"):
        yield Variants(celms[:-2] + "ll", I_MIJA, "ll -> ļļ")
    elif celms.endswith("ņņ"):
        yield Variants(celms[:-2] + "nn", I_MIJA, "nn -> ņņ")
    elif celms.endswith("č"):
        yield Variants(celms[:-1] + "c", I_MIJA, "c -> č")
    elif celms.endswith("ž"):
        yield Variants(celms[:-1] + "d", I_MIJA, "d -> ž")
        yield Variants(celms[:-1] + "z", I_MIJA, "z -> ž")
    elif celms.endswith("š"):
        yield Variants(celms[:-1] + "t", I_MIJA, "t -> š")
        yield Variants(celms[:-1] + "s", I_MIJA, "s -> š")
    elif celms.endswith("ķ"):
        yield Variants(celms[:-1] + "k", I_MIJA, "k -> ķ")
    elif celms.endswith("ļ"):
        yield Variants(celms[:-1] + "l", I_MIJA, "l -> ļ")
    elif celms.endswith("ņ"):
        yield Variants(celms[:-1] + "n", I_MIJA, "n -> ņ")
    else:
        yield Variants(celms)


def _case_102(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG noun consonant softening for e/i/ē/ī/ie endings."""
    if celms.endswith("kš"):
        yield Variants(celms[:-2] + "kst", I_MIJA, "kst -> kš")
    elif celms.endswith("šl"):
        yield Variants(celms[:-2] + "šļ", I_MIJA, "šļ -> šl")
        yield Variants(celms[:-2] + "sl", I_MIJA, "sl -> šl")
    elif celms.endswith("žl"):
        yield Variants(celms[:-2] + "žļ", I_MIJA, "žļ -> žl")
        yield Variants(celms[:-2] + "zl", I_MIJA, "zl -> žl")
    elif celms.endswith("šm"):
        yield Variants(celms[:-2] + "šm", I_MIJA, "šm -> šm")
        yield Variants(celms[:-2] + "sm", I_MIJA, "sn -> šn")
    elif celms.endswith("šn"):
        yield Variants(celms[:-2] + "šņ", I_MIJA, "šņ -> šn")
        yield Variants(celms[:-2] + "sn", I_MIJA, "sn -> šn")
    elif celms.endswith("žn"):
        yield Variants(celms[:-2] + "žņ", I_MIJA, "žņ -> žn")
        yield Variants(celms[:-2] + "zn", I_MIJA, "zn -> žn")
    elif celms.endswith("ll"):
        yield Variants(celms[:-2] + "ļļ", I_MIJA, "ļļ -> ll")
    elif celms.endswith("nn"):
        yield Variants(celms[:-2] + "ņņ", I_MIJA, "ņņ -> nn")
    elif celms.endswith("č"):
        yield Variants(celms[:-1] + "c", I_MIJA, "c -> č")
    elif celms.endswith("š"):
        yield Variants(celms[:-1] + "t", I_MIJA, "t -> š")
        yield Variants(celms[:-1] + "s", I_MIJA, "s -> š")
    elif celms.endswith("ž"):
        yield Variants(celms[:-1] + "d", I_MIJA, "d -> ž")
        yield Variants(celms[:-1] + "z", I_MIJA, "z -> ž")
    elif celms.endswith("l"):
        yield Variants(celms[:-1] + "ļ", I_MIJA, "ļ -> l")
    elif celms.endswith("n"):
        yield Variants(celms[:-1] + "ņ", I_MIJA, "ņ -> n")
    elif celms.endswith("k"):
        yield Variants(celms[:-1] + "ķ", I_MIJA, "ķ -> k")
    elif celms.endswith("g"):
        yield Variants(celms[:-1] + "ģ", I_MIJA, "ģ -> g")
    else:
        yield Variants(celms)


def _case_103(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG adjective -uok- + vys-/vysu-."""
    yield from _ltg_emit_uok_with_degree(celms)
    yield Variants(celms, attributes=_ltg_degree_flags(V_POSITIVE))


def _case_104(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG adjective -uok- + vys-/vysu-, with burtu mija on positive degree."""
    if celms.endswith("uok") and len(celms) > 3:
        yield from _ltg_emit_uok_with_degree(celms)
    else:
        yield Variants(_ltg_burtu_mija_atpakal_viennoz(celms),
                       attributes=_ltg_degree_flags(V_POSITIVE))


def _case_105(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG -uoka with -ajam-style endings."""
    if celms.endswith("uoka") and len(celms) > 4:
        stem, degree = _strip_vys(celms)
        yield Variants(stem[:-4], attributes=_ltg_degree_flags(degree))
    if celms.endswith("a"):
        yield Variants(celms[:-1], attributes=_ltg_degree_flags(V_POSITIVE))
    elif celms.endswith(("ē", "e")):
        yield Variants(celms + "j", attributes=_ltg_degree_flags(V_POSITIVE))


def _case_106(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG adverb -uok- + vys-/vysu-."""
    yield from _ltg_emit_uok_with_degree(celms)


def _case_107(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG burtu mija inverse — when lemma ending is -e/-i/-ī/-ē/-ie."""
    yield Variants(_ltg_burtu_mija(celms))


def _case_108(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG slapnis-style: 107 (burtu mija) + 106 (vys-uok)."""
    yield from _ltg_emit_uok_with_degree(celms, _ltg_burtu_mija)


def _case_109(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG adverbs with degree gradation, no burtu mija."""
    if not (celms.endswith("uok") and len(celms) > 4):
        yield Variants(celms, attributes=_ltg_degree_flags(V_POSITIVE))
        return
    stem, degree = _strip_vys(celms)
    base = stem[:-3]
    for suffix in ("", "i", "a", "ai"):
        yield Variants(base + suffix, attributes=_ltg_degree_flags(degree))


def _case_110(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple present mija."""
    if celms.endswith("e"):
        yield Variants(celms[:-1] + "ei", I_MIJA, "ei -> e")
        yield Variants(celms[:-1] + "ē", I_MIJA, "ē -> e")
    elif celms.endswith("o"):
        yield Variants(celms[:-1] + "uo", I_MIJA, "uo -> o")


def _case_111(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple-past 1st/2nd person singular mija."""
    if celms.endswith("uoj"):
        yield Variants(celms[:-1], I_MIJA, "uo -> uoj")
    elif celms.endswith("ov"):
        yield Variants(celms[:-2] + "uo", I_MIJA, "uo -> ov")
    elif celms.endswith("iej"):
        yield Variants(celms[:-3] + "ē", I_MIJA, "ē -> iej")
    elif celms.endswith("ej"):
        yield Variants(celms[:-2] + "ie", I_MIJA, "ei -> ej")


def _case_112(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple-past plural and 3rd-person mija."""
    if celms.endswith("uoj"):
        yield Variants(celms[:-1], I_MIJA, "uo -> uoj")
    elif celms.endswith("ov"):
        yield Variants(celms[:-2] + "uo", I_MIJA, "uo -> ov")
    elif celms.endswith("ēj"):
        yield Variants(celms[:-1], I_MIJA, "ē -> ēj")
    elif celms.endswith("ej"):
        yield Variants(celms[:-2] + "ie", I_MIJA, "ei -> ej")


def _case_113(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj simple-future 1st/2nd person singular mija."""
    if celms.endswith("ie"):
        yield Variants(celms[:-2] + "ē", I_MIJA, "ē -> ie")
    elif celms.endswith(("uo", "ei")):
        yield Variants(celms)


def _case_114(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj subjunctive, supinum, passive past (-ts) participle, -dams."""
    if celms.endswith("ā"):
        yield Variants(celms[:-1] + "ē", I_MIJA, "ē -> ā")
    elif celms.endswith(("uo", "ei")):
        yield Variants(celms)


def _case_115(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj participle superlative + present mija (110 with degree)."""
    stem, degree = _strip_vys(celms)
    if stem.endswith("e"):
        yield Variants(stem[:-1] + "ei", attributes=_ltg_degree_flags(degree))
        yield Variants(stem[:-1] + "ē",  attributes=_ltg_degree_flags(degree))
    elif stem.endswith("o"):
        yield Variants(stem[:-1] + "uo", attributes=_ltg_degree_flags(degree))


def _case_116(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj participle superlative + subjunctive/supinum mija (-ts participle)."""
    stem, degree = _strip_vys(celms)
    if stem.endswith("ā"):
        yield Variants(stem[:-1] + "ē", attributes=_ltg_degree_flags(degree))
    elif stem.endswith(("uo", "ei")):
        yield Variants(stem, attributes=_ltg_degree_flags(degree))


def _case_117(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj past mija for -s, -use participle (simplified 111)."""
    if celms.endswith("uo"):
        yield Variants(celms)
    elif celms.endswith("ie"):
        yield Variants(celms[:-2] + "ē", I_MIJA, "ē -> ie")
    elif celms.endswith("e"):
        yield Variants(celms[:-1] + "ie", I_MIJA, "ei -> e")


def _case_118(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 2nd-conj participle superlative + past mija for -s, -use (117)."""
    stem, degree = _strip_vys(celms)
    if stem.endswith("ie"):
        yield Variants(stem[:-2] + "ē", attributes=_ltg_degree_flags(degree))
    elif stem.endswith("e"):
        yield Variants(stem[:-1] + "ie", attributes=_ltg_degree_flags(degree))
    elif stem.endswith("uo"):
        yield Variants(stem, attributes=_ltg_degree_flags(degree))


def _case_119(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -eit (no consonant mija)."""
    yield Variants(celms + "ei", I_MIJA, "ei -> ")


def _case_120(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -eit no-mija + participle superlative (119 with degree)."""
    stem, degree = _strip_vys(celms)
    yield Variants(stem + "ei", attributes=_ltg_degree_flags(degree))


def _case_121(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj participle superlative without mija."""
    stem, degree = _strip_vys(celms)
    yield Variants(stem, attributes=_ltg_degree_flags(degree))


def _case_122(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -eit, present with consonant mija."""
    for r in _LTG_3RD_EIT_MIJA:
        if celms.endswith(r.match):
            yield Variants(celms[:-len(r.match)] + r.replace, I_MIJA, r.note)
            return


def _case_123(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -eit consonant mija + participle superlative (122 with degree)."""
    stem, degree = _strip_vys(celms)
    for r in _LTG_3RD_EIT_MIJA:
        if stem.endswith(r.match):
            yield Variants(stem[:-len(r.match)] + r.replace,
                           attributes=_ltg_degree_flags(degree))
            return


def _case_124(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj standard -ēt (no consonant or letter mija)."""
    yield Variants(celms + "ē", I_MIJA, "ē -> ")


def _case_125(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -ēt with letter mija."""
    yield Variants(_ltg_burtu_mija(celms) + "ē", I_MIJA, "ē -> ")


def _case_126(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -ēt no consonant/letter mija + participle superlative."""
    stem, degree = _strip_vys(celms)
    yield Variants(stem + "ē", attributes=_ltg_degree_flags(degree))


def _case_127(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """LTG 3rd-conj -ēt with inverse letter mija + participle superlative."""
    stem, degree = _strip_vys(celms)
    yield Variants(_ltg_burtu_mija(stem) + "ē",
                   attributes=_ltg_degree_flags(degree))


# ===========================================================================
# Inflection (generation) direction (`_inf_99..127`).
# ===========================================================================


def _inf_99(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    yield Variants(_ltg_burtu_mija(celms))


def _inf_100(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    yield Variants(_ltg_burtu_mija(celms))


def _inf_101(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    """LTG noun consonant mija (forward direction of case 101)."""
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


def _inf_102(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    """LTG noun consonant softening (forward direction of case 102)."""
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


def _inf_uok_emit(celms: str, add_super: bool, *, transform=None) -> Iterator[Variants]:
    """Cases 103/104/106/108 inflection share: yield comparative `+uok` and
    optional `vys-/vysu-` superlatives, with an optional stem transform first."""
    if celms.endswith("uok"):
        return
    base = transform(celms) if transform else celms
    yield Variants(base + "uok", attributes=_ltg_degree_flags(V_COMPARATIVE))
    if add_super:
        yield Variants("vys" + base + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))
        yield Variants("vysu" + base + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _inf_103(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    yield Variants(celms, attributes=_ltg_degree_flags(V_POSITIVE))
    yield from _inf_uok_emit(celms, supr)


def _inf_104(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    yield Variants(_ltg_burtu_mija(celms), attributes=_ltg_degree_flags(V_POSITIVE))
    yield from _inf_uok_emit(celms, supr)


def _inf_105(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith(("ēj", "ej")):
        yield Variants(celms[:-1], attributes=_ltg_degree_flags(V_POSITIVE))
    else:
        yield Variants(celms + "a", attributes=_ltg_degree_flags(V_POSITIVE))
    yield Variants(celms + "uoka", attributes=_ltg_degree_flags(V_COMPARATIVE))
    if supr:
        yield Variants("vys" + celms + "uoka", attributes=_ltg_degree_flags(V_SUPERLATIVE))
        yield Variants("vysu" + celms + "uoka", attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _inf_106(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    yield from _inf_uok_emit(celms, supr)


def _inf_107(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    yield Variants(_ltg_burtu_mija_atpakal_viennoz(celms))


def _inf_108(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    yield from _inf_uok_emit(celms, supr, transform=_ltg_burtu_mija_atpakal_viennoz)


def _inf_109(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    yield Variants(celms, attributes=_ltg_degree_flags(V_POSITIVE))
    if celms.endswith("ai"):
        celms = celms[:-2]
    elif celms.endswith(("i", "a")):
        celms = celms[:-1]
    yield Variants(celms + "uok", attributes=_ltg_degree_flags(V_COMPARATIVE))
    if supr:
        yield Variants("vys" + celms + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))
        yield Variants("vysu" + celms + "uok", attributes=_ltg_degree_flags(V_SUPERLATIVE))


def _inf_110(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("uo"):
        yield Variants(celms[:-2] + "o")
    elif celms.endswith("ei"):
        yield Variants(celms[:-2] + "e")
    elif celms.endswith("ē"):
        yield Variants(celms[:-1] + "e")


def _inf_111(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("uo"):
        yield Variants(celms + "j")
        yield Variants(celms[:-2] + "ov")
    elif celms.endswith("ei"):
        yield Variants(celms[:-2] + "ej")
    elif celms.endswith("ē"):
        yield Variants(celms[:-1] + "iej")


def _inf_112(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("uo"):
        yield Variants(celms + "j")
        yield Variants(celms[:-2] + "ov")
    elif celms.endswith("ei"):
        yield Variants(celms[:-2] + "ej")
    elif celms.endswith("ē"):
        yield Variants(celms + "j")


def _inf_113(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("ē"):
        yield Variants(celms[:-1] + "ie")
    elif celms.endswith(("ei", "uo")):
        yield Variants(celms)


def _inf_114(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("ē"):
        yield Variants(celms[:-1] + "ā")
    elif celms.endswith(("ei", "uo")):
        yield Variants(celms)


def _inf_115(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("uo"):
        yield from _ltg_super_emit(celms[:-2] + "o", supr)
    elif celms.endswith("ei"):
        yield from _ltg_super_emit(celms[:-2] + "e", supr)
    elif celms.endswith("ē"):
        yield from _ltg_super_emit(celms[:-1] + "e", supr)


def _inf_116(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("ē"):
        yield from _ltg_super_emit(celms[:-1] + "ā", supr)
    elif celms.endswith(("ei", "uo")):
        yield from _ltg_super_emit(celms, supr)


def _inf_117(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("uo"):
        yield Variants(celms)
    elif celms.endswith("ei"):
        yield Variants(celms[:-2] + "e")
    elif celms.endswith("ē"):
        yield Variants(celms[:-1] + "ie")


def _inf_118(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("ei"):
        yield from _ltg_super_emit(celms[:-2] + "e", supr)
    elif celms.endswith("ē"):
        yield from _ltg_super_emit(celms[:-1] + "ie", supr)
    elif celms.endswith("uo"):
        yield from _ltg_super_emit(celms, supr)


def _inf_119(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("ei"):
        yield Variants(celms[:-2])


def _inf_120(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("ei"):
        yield from _ltg_super_emit(celms[:-2], supr)


def _inf_121(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    yield from _ltg_super_emit(celms, supr)


def _inf_3rd_eit_base(celms: str) -> str | None:
    """Common stem extraction for cases 122/123 inflection."""
    for r in _LTG_3RD_EIT_MIJA_REV:
        if celms.endswith(r.match):
            return celms[:-len(r.match)] + r.replace
    return None


def _inf_122(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    base = _inf_3rd_eit_base(celms)
    if base is not None:
        yield Variants(base)


def _inf_123(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    base = _inf_3rd_eit_base(celms)
    if base is not None:
        yield from _ltg_super_emit(base, supr)


def _inf_124(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("ē"):
        yield Variants(celms[:-1])


def _inf_125(celms: str, _t: str, _s: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("ē"):
        yield Variants(_ltg_burtu_mija_atpakal_viennoz(celms[:-1]))


def _inf_126(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("ē"):
        yield from _ltg_super_emit(celms[:-1], supr)


def _inf_127(celms: str, _t: str, supr: bool, _p: bool) -> Iterator[Variants]:
    if celms.endswith("ē"):
        yield from _ltg_super_emit(_ltg_burtu_mija_atpakal_viennoz(celms[:-1]), supr)


# ---------------------------------------------------------------------------
# Dispatcher tables — merged into `mijas._HANDLERS_*` at import time.
# ---------------------------------------------------------------------------

LTG_HANDLERS_VARIANTS: dict[int, Callable[[str, bool], Iterator[Variants]]] = {
    99: _case_99, 100: _case_100, 101: _case_101, 102: _case_102, 103: _case_103,
    104: _case_104, 105: _case_105, 106: _case_106, 107: _case_107, 108: _case_108,
    109: _case_109, 110: _case_110, 111: _case_111, 112: _case_112, 113: _case_113,
    114: _case_114, 115: _case_115, 116: _case_116, 117: _case_117, 118: _case_118,
    119: _case_119, 120: _case_120, 121: _case_121, 122: _case_122, 123: _case_123,
    124: _case_124, 125: _case_125, 126: _case_126, 127: _case_127,
}

LTG_HANDLERS_INFLECTION: dict[int, Callable[[str, str, bool, bool], Iterator[Variants]]] = {
    99: _inf_99, 100: _inf_100, 101: _inf_101, 102: _inf_102, 103: _inf_103,
    104: _inf_104, 105: _inf_105, 106: _inf_106, 107: _inf_107, 108: _inf_108,
    109: _inf_109, 110: _inf_110, 111: _inf_111, 112: _inf_112, 113: _inf_113,
    114: _inf_114, 115: _inf_115, 116: _inf_116, 117: _inf_117, 118: _inf_118,
    119: _inf_119, 120: _inf_120, 121: _inf_121, 122: _inf_122, 123: _inf_123,
    124: _inf_124, 125: _inf_125, 126: _inf_126, 127: _inf_127,
}
