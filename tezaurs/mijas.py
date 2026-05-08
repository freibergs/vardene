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

from collections.abc import Callable, Iterator

from tezaurs.mijas_dsl import (
    I_DEGREE,
    I_MIJA,
    V_COMPARATIVE,
    V_POSITIVE,
    V_SUPERLATIVE,
    SuffixRule,
    _apply_all,
    _apply_first,
    _strip_vis,
    syllables,
)
from tezaurs.mijas_ltg import (
    LTG_HANDLERS_INFLECTION,
    LTG_HANDLERS_VARIANTS,
    _ltg_patskanu_mija_atpakal_locisanai,
    _ltg_patskanu_mija_locisanai,
)
from tezaurs.variants import Variants

# ---------------------------------------------------------------------------
# Mija rule tables.
#
# Each rule is `SuffixRule(match, replace)` — when a stem ends with `match`,
# strip those chars and append `replace`. Tables are *shared across cases*
# whenever cases differ only in degree-handling or other wrapping; e.g.
# `_3RD_AMS` is used by both case 27 (no degree) and case 33 (vis- prefix
# with degree marker).
#
# Principle: "function says HOW; table says WHAT." If a function's elif-chain
# does the same operation with different data, that data wants to be a list.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Shared rule tables (LV)
# ---------------------------------------------------------------------------

# 3rd-conj -ams/-āms (cases 27 + 33-with-degree). Case 33 also has a special
# "guļa" rule that overrides ļa here; we keep that case-local.
_3RD_AMS = (
    SuffixRule("kā", "cī", "sacīt"),
    SuffixRule("gā", "dzī", "slodzīt"),
    SuffixRule("ka", "cē", "mācēt -> mākam"),
    SuffixRule("ža", "dē", "sēdēt -> sēžam"),
    SuffixRule("ļa", "lē", "gulēt -> guļam"),
    SuffixRule("ga", "dzē", "vajadzēt -> vajag"),
)

# 3rd-conj 3rd-person present (case 30, with vajadz/vajag exceptions).
_3RD_3PS = (
    SuffixRule("ka", "cī", "sacīt"),
    SuffixRule("ga", "dzī", "slodzīt -> sloga"),
    SuffixRule("k", "cē", "mācēt -> māk"),
    SuffixRule("ž", "dē", "sēdēt -> sēž"),
    SuffixRule("ļ", "lē", "guļ -> gulēt"),
)

# 3rd-conj imperative / participle mija (cases 26, 32-with-degree). Multi-yield
# for k/g (two stems each); case 26 also has gul/tec/loc/moc/urc specials.
_3RD_IMP_MULTI = (
    SuffixRule("k", "cī", "saki -> sacīt"),
    SuffixRule("k", "cē", "māki -> mācēt"),
    SuffixRule("g", "dzī", "slogi -> slodzīt"),
    SuffixRule("g", "dzē", "vajag -> vajadzēt"),
    SuffixRule("ž", "dē", "sēdēt"),
    SuffixRule("ļ", "lē", "gulēt"),
)


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
    4: ("jā", 4, 0, False),
    5: ("jā", 4, 9, False),
    12: ("jā", 4, 8, False),
    19: ("jā", 4, 2, False),
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
        residue = stem[len(prefix) :]
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
    elif mija == 7 and celms.endswith(
        ("odi", "ūdi", "opi", "ūpi", "oti", "ūti", "īti", "ieti", "sti")
    ):
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


def _case_14(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """1st-conjugation -is form."""
    if celms.endswith("c"):
        yield Variants(celms[:-1] + "k")  # raku -> racis
        yield Variants(celms[:-1] + "c")  # veicu -> veicis
    elif celms.endswith("dz"):
        yield Variants(celms[:-2] + "g")  # sarūgu -> sarūdzis
        yield Variants(celms)  # lūdzu -> lūdzis
    else:
        yield Variants(celms)


def _case_15(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """pūst → pūzdams, nopūzdamies — s↔z mija."""
    yield Variants(celms)
    if celms.endswith("z"):
        yield Variants(celms[:-1] + "s")


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
        yield Variants(celms[:-1] + "lē")
    if celms.endswith("tec"):
        yield Variants(celms + "ē")
    elif celms.endswith("k") and not celms.endswith("tek"):
        yield Variants(celms[:-1] + "cī")
        yield Variants(celms[:-1] + "cē")
    elif celms.endswith("g"):
        yield Variants(celms[:-1] + "dzī")
        yield Variants(celms[:-1] + "dzē")
    elif celms.endswith(("loc", "moc", "urc")):
        yield Variants(celms + "ī")
    else:
        yield Variants(celms + "ē")


def _case_27(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """-ams/-āms 3rd-conjugation mija + we/you forms."""
    yield from _apply_first(celms, _3RD_AMS)


def _case_30(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """3rd-conjugation 3rd-person present with mija."""
    if celms.endswith("vajadz"):
        return  # 'vajadzēt' -> 'vajag' is the only correct form
    yield from _apply_first(celms, _3RD_3PS)
    if celms.endswith("vajag"):
        yield Variants(celms[:-1] + "dzē")  # vajadzēt -> vajag (special)


def _case_32(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Like case 20 but for comparative/superlative — visizsakošākais."""
    celms, pakape = _strip_vis(celms)
    yield from _apply_all(celms, _3RD_IMP_MULTI, I_DEGREE, pakape)


def _case_33(celms: str, _proper_name: bool) -> Iterator[Variants]:
    """Like case 27 but with comparative/superlative degrees for -amāks forms."""
    celms, pakape = _strip_vis(celms)
    # _3RD_AMS minus the ļa rule (case 33 uses guļa instead).
    if celms.endswith(("kā", "gā", "ka", "ga", "ža")):
        yield from _apply_first(celms, _3RD_AMS, I_DEGREE, pakape)
    elif celms.endswith("guļa"):
        yield Variants(celms[:-2] + "lē", I_DEGREE, pakape)


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
    **LTG_HANDLERS_VARIANTS,  # cases 99-127 from `mijas_ltg`
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


def _inf_7_or_23(celms: str, third_stem: str, mija: int) -> Iterator[Variants]:
    """1st-conjugation 2nd-person present (mija=7 short, mija=23 long-ending like -iet)."""
    if celms.endswith("š") and third_stem.endswith("s"):
        yield Variants(celms[:-1] + "s")
    elif celms.endswith("š") and third_stem.endswith("t"):
        yield Variants(celms[:-1] + "t")
    elif (celms.endswith("od") and not celms.endswith("dod")) or celms.endswith(
        ("ūd", "op", "ūp", "ot", "ūt", "īt", "iet", "st")
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
    elif celms.endswith("ē") or celms.endswith("ā"):
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
    elif celms.endswith("ē") or celms.endswith("ā"):
        yield Variants(celms[:-1] + "a", I_DEGREE, V_COMPARATIVE)
    else:
        yield Variants(celms, I_DEGREE, V_COMPARATIVE)
    if add_superlative:
        if celms.endswith(("inā", "sargā")):
            yield Variants("vis" + celms, I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("ī"):
            yield Variants("vis" + celms[:-1] + "ā", I_DEGREE, V_SUPERLATIVE)
        elif celms.endswith("ē") or celms.endswith("ā"):
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
        elif celms.endswith("vajadzē") or celms.endswith(("dzī", "dzē")):
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


def _inf_7(celms: str, third_stem: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    return _inf_7_or_23(celms, third_stem, mija=7)


def _inf_23(celms: str, third_stem: str, _supr: bool, _proper: bool) -> Iterator[Variants]:
    return _inf_7_or_23(celms, third_stem, mija=23)


_HANDLERS_INFLECTION: dict[int, Callable[[str, str, bool, bool], Iterator[Variants]]] = {
    0: _inf_0,
    1: _inf_1,
    2: _inf_2,
    3: _inf_3,
    6: _inf_6,
    7: _inf_7,
    8: _inf_8,
    9: _inf_9,
    10: _inf_10,
    11: _inf_11,
    13: _inf_13,
    14: _inf_14,
    15: _inf_15,
    16: _inf_16,
    17: _inf_17,
    20: _inf_20,
    21: _inf_21,
    22: _inf_22,
    23: _inf_23,
    24: _inf_24,
    25: _inf_25,
    26: _inf_26,
    27: _inf_27,
    30: _inf_30,
    32: _inf_32,
    33: _inf_33,
    34: _inf_34,
    35: _inf_35,
    36: _inf_36,
    38: _inf_38,
    **LTG_HANDLERS_INFLECTION,  # cases 99-127 from `mijas_ltg`
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
