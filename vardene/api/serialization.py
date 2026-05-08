"""JSON serializers for Wordform / Variants.

Two flavours:
  - Latvian attribute names (`lv`): default, matches `tagset.json` LV labels.
  - English attribute names (`en`): translates both attribute keys and values
    via the tagset's English fields.
"""

from __future__ import annotations

from typing import Any

from vardene.attributes import TagSet
from vardene.markup import to_tag
from vardene.wordform import Wordform


def wordform_to_dict(wf: Wordform, *, language: str = "lv") -> dict[str, Any]:
    """Serialise a Wordform to a JSON-friendly dict.

    `language='lv'` keeps the original Latvian attribute names; `language='en'`
    translates them via the tagset.
    """
    tag = to_tag(wf)
    lemma = wf.get("Pamatforma") or (wf.lexeme.lemma if wf.lexeme else None)
    paradigm = wf.ending.paradigm.name if wf.ending and wf.ending.paradigm else None
    attrs: dict[str, str] = dict(wf)
    if language == "en":
        attrs = _translate_attrs_to_english(attrs)
    return {
        "token": wf.token,
        "lemma": lemma,
        "tag": tag,
        "paradigm": paradigm,
        "attributes": attrs,
    }


def _translate_attrs_to_english(attrs: dict) -> dict:
    """Translate attribute keys and values from Latvian to English where the
    tagset has `en` fields."""
    ts = TagSet.instance()
    out: dict[str, str] = {}
    for key, value in attrs.items():
        attr = ts.by_lv(key)
        en_key = attr.en if attr is not None and attr.en else key
        en_value = str(value)
        if attr is not None:
            v = attr.value_by_lv(str(value))
            if v is not None and v.en:
                en_value = v.en
        out[en_key] = en_value
    return out
