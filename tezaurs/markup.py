"""MarkupConverter / TagSet positional tag string formatting.

Port of `attributes/TagSet.java` `toTag` and the data-driven half of
`analyzer/MarkupConverter.java` (884 LOC Java; the MarkupConverter is marked
`@Deprecated` in favor of `TagSet.toTag` which reads tagset.xml directly).

Tag format examples (Semti-Kamols):
  ncmsn1   — noun, common, masculine, singular, nominative, declension 1
  vmnipi330an — verb, main, indicative, present, indicative, 3rd person, ...
  ncfsn5   — noun, common, feminine, singular, nominative, declension 5
  zs       — punctuation, sentence

`to_tag(av)` — emit the positional string from an `AttributeValues` (or any
mapping with LV-keyed grammatical values).
`from_tag(tag)` — inverse: parse a tag string back to LV attribute values
using the POS char to pick the correct attribute layout.
"""

from __future__ import annotations

from collections.abc import Mapping

from tezaurs.attributes import AttributeValues, TagAttribute, TagSet

POS_LV = "Vārdšķira"


# The lexicon and the tagset diverged in places — the lexicon uses some plural
# or alternative forms for attribute names and values that the tagset doesn't
# list explicitly. We translate to the tagset's canonical form on lookup.
_ATTR_ALIASES: dict[str, str] = {
    "Saikļa tips": "Saikļa sintaktiskā funkcija",
}

_VALUE_ALIASES: dict[str, dict[str, str]] = {
    "Vietniekvārda tips": {
        "Jautājamie": "Jautājamais",
        "Norādāmie": "Norādāmais",
        "Personīgie": "Personas",
        "Personu": "Personas",
        "Noteiktie": "Noteiktais",
        "Nenoteiktie": "Nenoteiktais",
        "Atgriezeniskie": "Atgriezeniskais",
        "Piederības vietniekvārds": "Piederības",
    },
    "Novietojums": {
        "Pirms": "Prepozitīvs",
        "Pēc": "Postpozitīvs",
    },
}


def _resolve_attr(av, attr_name: str, tagset) -> tuple[str, str | None]:
    """Look up the LV value for attribute `attr_name`, applying aliases when
    the lexicon's name diverges from the tagset's."""
    canonical_attr = _ATTR_ALIASES.get(attr_name, attr_name)
    raw = av.get(attr_name) if hasattr(av, "get") else None
    if raw is None and canonical_attr != attr_name:
        raw = av.get(canonical_attr)
    if raw is None:
        return canonical_attr, None
    aliases = _VALUE_ALIASES.get(attr_name) or _VALUE_ALIASES.get(canonical_attr)
    if aliases:
        raw = aliases.get(raw, raw)
    return canonical_attr, raw


def to_tag(av: AttributeValues | Mapping[str, str], tagset: TagSet | None = None) -> str:
    """Encode `av` as a Semti-Kamols positional tag string.

    Returns `"-"` if no Vārdšķira (POS) is set — matches Java behaviour for
    unrecognized words.
    """
    if tagset is None:
        tagset = TagSet.instance()

    pos_value = av.get(POS_LV) if hasattr(av, "get") else None
    if pos_value is None:
        return "-"

    pos_attr = tagset.by_lv(POS_LV)
    if pos_attr is None:
        return "-"
    pos_tag_value = pos_attr.value_by_lv(pos_value)
    if pos_tag_value is None or pos_tag_value.tag is None:
        return "-"

    # Participle dispatch: when verb + Izteiksme=Divdabis, switch to the
    # participle-specific attribute layout (Lokāmība/Dzimte/Skaitlis/...).
    # This mirrors Java's `POS_BASED_SEMTI` exception in TagSet.toTag.
    layout_pos = pos_value
    is_participle = pos_value == "Darbības vārds" and av.get("Izteiksme") == "Divdabis"
    if is_participle:
        layout_pos = "Divdabis"

    # Seed the buffer with default_tags so unspecified positions get sensible chars
    buf = list(pos_tag_value.default_tags or pos_tag_value.tag)
    if not buf:
        buf = [pos_tag_value.tag]

    # Walk every attribute that applies to the chosen POS layout.
    pos_specific = list(tagset.attributes_for_pos(layout_pos))
    for attribute in pos_specific:
        _set_position(av, buf, attribute)

    # Some attributes apply to all POS — skip those handled above.
    seen = {a.lv for a in pos_specific}
    for attribute in tagset.attributes:
        if attribute.markup_pos is None or attribute.lv == POS_LV:
            continue
        if attribute.part_of_speech is not None and attribute.lv not in seen:
            continue
        if attribute.lv in seen:
            continue
        _set_position(av, buf, attribute)

    # Final pass: apply POS-specific defaults for positions still left as '_'.
    # The Java tagger ships with `defaulti=true` mode which fills in conventional
    # values (verbs are intransitive unless declared otherwise; etc).
    _apply_default_fillins(pos_value, buf)
    return "".join(buf)


# Reasonable defaults the Java tagger emits when a position is unset.
# These match what `api.tezaurs.lv` returns in practice.
# Values reflect majority class in the training corpus; lexicon-declared
# attributes always override these.
_POS_DEFAULTS: dict[str, dict[int, str]] = {
    "Darbības vārds": {
        1: "m",  # Darbības vārda tips = Patstāvīgs
        2: "n",  # Atgriezeniskums = Nē
        5: "i",  # Transitivitāte = Intransitīvs (slight majority in lexicon)
        10: "n",  # Noliegums = Nē
    },
    "Lietvārds": {
        1: "c",  # Lietvārda tips = Sugas vārds
    },
    "Saiklis": {
        1: "c",  # Sakārtojuma (most common: un, vai, bet, jeb)
    },
    "Vietniekvārds": {
        1: "r",  # Attieksmes (most common in corpus per gold)
        2: "3",  # Persona = 3 (most demonstrative/possessive pronouns)
        6: "n",  # Noliegums = Nē
    },
}


def _apply_default_fillins(pos_value: str, buf: list[str]) -> None:
    defaults = _POS_DEFAULTS.get(pos_value)
    if not defaults:
        return
    for pos, ch in defaults.items():
        if pos < len(buf) and buf[pos] == "_":
            buf[pos] = ch


def _set_position(
    av: AttributeValues | Mapping[str, str],
    buf: list[str],
    attribute: TagAttribute,
) -> None:
    if attribute.markup_pos is None:
        return
    # Try the canonical attribute name first; fall back to lexicon-side aliases.
    actual = av.get(attribute.lv)  # type: ignore[arg-type]
    if actual is None:
        # Some attributes are stored in the lexicon under a different name
        # (e.g. "Saikļa tips" maps to canonical "Saikļa sintaktiskā funkcija").
        for lex_name, canonical_name in _ATTR_ALIASES.items():
            if canonical_name == attribute.lv:
                actual = av.get(lex_name)  # type: ignore[arg-type]
                if actual is not None:
                    break
    if actual is None:
        return
    # Coerce non-string values (e.g. Persona arrives as int 2 from the parquet).
    if not isinstance(actual, str):
        actual = str(actual)
    # Translate alias values (e.g. "Jautājamie" → "Jautājamais") if needed.
    aliases = _VALUE_ALIASES.get(attribute.lv)
    if aliases:
        actual = aliases.get(actual, actual)
    # Also check aliases keyed under the lexicon-side name.
    for lex_name in _ATTR_ALIASES:
        if _ATTR_ALIASES[lex_name] == attribute.lv:
            extra = _VALUE_ALIASES.get(lex_name)
            if extra:
                actual = extra.get(actual, actual)
    value = attribute.value_by_lv(actual)
    if value is None or value.tag is None:
        return
    pos = attribute.markup_pos
    while len(buf) <= pos:
        buf.append("_")
    buf[pos] = value.tag


def from_tag(tag: str, tagset: TagSet | None = None) -> AttributeValues:
    """Decode a positional tag string back to `AttributeValues`.

    First char selects the POS, then later positions are looked up against
    each attribute's `markup_pos` field.
    """
    av = AttributeValues()
    if not tag or tag == "-":
        return av
    if tagset is None:
        tagset = TagSet.instance()

    pos_attr = tagset.by_lv(POS_LV)
    if pos_attr is None:
        return av
    pos_value = pos_attr.value_by_tag(tag[0])
    if pos_value is None:
        return av
    av.add(POS_LV, pos_value.lv)

    for attribute in tagset.attributes_for_pos(pos_value.lv):
        if attribute.markup_pos is None or attribute.markup_pos >= len(tag):
            continue
        ch = tag[attribute.markup_pos]
        if ch in ("_", "-"):
            continue
        v = attribute.value_by_tag(ch)
        if v is not None:
            av.add(attribute.lv, v.lv)
    return av
