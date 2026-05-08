"""Grammatical attributes — Python port of `attributes/AttributeValues.java` and `TagSet.java`.

`AttributeValues` is a bag of (key, value) pairs describing a morphological
analysis (e.g. `{"Vārdšķira": "Lietvārds", "Locījums": "Nominatīvs"}`).
Values may be pipe-separated for multi-valued attributes (e.g. `"Lietvārds|Īpašības vārds"`).

`TagSet` is a singleton that loads `data/tagset.json` and exposes lookups by
LV attribute name and by part-of-speech.

API kept 1:1 with the Java upstream where it makes sense; renamed to snake_case.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import ClassVar

_MULTIVALUE_SEP = "|"


def _ci_match(actual: str, expected: str) -> bool:
    """Java `equalsIgnoreCase` equivalent. Pipe-separated `actual` matches if any value matches."""
    if _MULTIVALUE_SEP in actual:
        return any(part.casefold() == expected.casefold() for part in actual.split(_MULTIVALUE_SEP))
    return actual.casefold() == expected.casefold()


class AttributeValues:
    """A bag of grammatical features. Mirrors the Java `AttributeValues` API."""

    __slots__ = ("_attrs",)

    def __init__(self, source: Mapping[str, str] | AttributeValues | None = None) -> None:
        if source is None:
            self._attrs: dict[str, str] = {}
        elif isinstance(source, AttributeValues):
            self._attrs = dict(source._attrs)
        else:
            self._attrs = dict(source)

    # --- single-attribute access ----------------------------------------

    def add(self, attribute: str, value: str) -> None:
        """Set an attribute value (overwrites if present)."""
        self._attrs[attribute] = value

    def remove(self, attribute: str) -> None:
        """Drop the attribute if present (no-op otherwise)."""
        self._attrs.pop(attribute, None)

    def get(self, attribute: str) -> str | None:
        return self._attrs.get(attribute)

    # --- bulk operations ------------------------------------------------

    def add_all(self, other: Mapping[str, str] | AttributeValues) -> None:
        if isinstance(other, AttributeValues):
            self._attrs.update(other._attrs)
        else:
            self._attrs.update(other)

    def filter_to(self, keep: Iterable[str]) -> None:
        """Drop every attribute not in `keep` (Java `filterAttributes`)."""
        keep_set = set(keep)
        self._attrs = {k: v for k, v in self._attrs.items() if k in keep_set}

    def clear(self) -> None:
        self._attrs.clear()

    # --- matching semantics --------------------------------------------

    def is_matching_strong(
        self, attribute_or_other: str | AttributeValues, value: str | None = None
    ) -> bool:
        """Strong match: attribute exists *and* value matches (or both are absent).

        Two-argument form: scalar `(attr, val)`. Single-argument form: bidirectional
        check against another `AttributeValues` (every key in either side must match).
        """
        if isinstance(attribute_or_other, AttributeValues):
            other = attribute_or_other
            return self._matches_strong_each(other) and other._matches_strong_each(self)
        actual = self._attrs.get(attribute_or_other)
        if actual is None and value is None:
            return True
        if actual is None:
            return False
        return _ci_match(actual, value or "")

    def is_matching_strong_one_side(self, other: AttributeValues) -> bool:
        """Every attribute in `other` must strongly match in self (no reverse check)."""
        return self._matches_strong_each(other)

    def is_matching_weak(
        self, attribute_or_other: str | AttributeValues, value: str | None = None
    ) -> bool:
        """Weak match: attribute either matches or is absent.

        Two-argument: scalar. Single-argument: every key in `other` weakly matches in self.
        """
        if isinstance(attribute_or_other, AttributeValues):
            other = attribute_or_other
            return all(self.is_matching_weak(k, v) for k, v in other._attrs.items())
        actual = self._attrs.get(attribute_or_other)
        if actual is None:
            return True
        return _ci_match(actual, value or "")

    def _matches_strong_each(self, other: AttributeValues) -> bool:
        return all(self.is_matching_strong(k, v) for k, v in other._attrs.items())

    # --- container protocol --------------------------------------------

    def __contains__(self, attribute: object) -> bool:
        return attribute in self._attrs

    def __getitem__(self, attribute: str) -> str:
        return self._attrs[attribute]

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self._attrs.items())

    def __len__(self) -> int:
        return len(self._attrs)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AttributeValues):
            return self._attrs == other._attrs
        return NotImplemented

    def __hash__(self) -> int:  # immutable view of the bag
        return hash(frozenset(self._attrs.items()))

    def __repr__(self) -> str:
        body = ", ".join(f"{k}={v!r}" for k, v in self._attrs.items())
        return f"AttributeValues({body})"

    # --- conversion ----------------------------------------------------

    def to_dict(self) -> dict[str, str]:
        """Plain dict copy. Keys are LV attribute names, values are LV value names."""
        return dict(self._attrs)

    def to_json(self) -> str:
        return json.dumps(self._attrs, ensure_ascii=False, sort_keys=True)

    def clone(self) -> AttributeValues:
        return AttributeValues(self)


# ---------------------------------------------------------------------------
# TagSet: singleton view over data/tagset.json
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TagValue:
    lv: str
    en: str | None
    tag: str | None  # single-char compact tag
    default_tags: str | None
    gf: str | None


@dataclass(frozen=True, slots=True)
class TagAttribute:
    lv: str
    en: str | None
    description: str | None
    part_of_speech: str | None  # LV name of POS this attribute applies to, or None for global
    markup_pos: int | None  # position in the compact markup tag string
    gf: str | None
    values: tuple[TagValue, ...] = field(default_factory=tuple)

    def value_by_lv(self, lv: str) -> TagValue | None:
        for v in self.values:
            if v.lv == lv:
                return v
        return None

    def value_by_tag(self, tag: str) -> TagValue | None:
        for v in self.values:
            if v.tag == tag:
                return v
        return None


class TagSet:
    """Singleton catalog of all grammatical attributes. Loads `data/tagset.json` once."""

    _DEFAULT_FILENAME: ClassVar[str] = "tagset.json"
    _instance: ClassVar[TagSet | None] = None

    __slots__ = ("_by_lv", "_pos_to_attrs", "attributes", "free_attributes")

    def __init__(
        self,
        attributes: tuple[TagAttribute, ...],
        free_attributes: tuple[Mapping[str, str], ...],
    ) -> None:
        self.attributes: tuple[TagAttribute, ...] = attributes
        self.free_attributes: tuple[Mapping[str, str], ...] = free_attributes
        self._by_lv: dict[str, TagAttribute] = {a.lv: a for a in attributes}
        self._pos_to_attrs: dict[str, list[TagAttribute]] = {}
        for a in attributes:
            if a.part_of_speech:
                self._pos_to_attrs.setdefault(a.part_of_speech, []).append(a)

    @classmethod
    def load(cls, json_path: Path | None = None) -> TagSet:
        path = json_path if json_path is not None else cls._default_data_path()
        with Path(path).open(encoding="utf-8") as f:
            data = json.load(f)
        attrs = tuple(
            TagAttribute(
                lv=a["lv"],
                en=a.get("en"),
                description=a.get("description"),
                part_of_speech=a.get("part_of_speech"),
                markup_pos=a.get("markup_pos"),
                gf=a.get("gf"),
                values=tuple(
                    TagValue(
                        lv=v["lv"],
                        en=v.get("en"),
                        tag=v.get("tag"),
                        default_tags=v.get("default_tags"),
                        gf=v.get("gf"),
                    )
                    for v in a["values"]
                ),
            )
            for a in data["attributes"]
        )
        free = tuple(data.get("free_attributes", ()))
        return cls(attrs, free)

    @classmethod
    def instance(cls) -> TagSet:
        """Lazily-loaded singleton from the package's bundled `data/tagset.json`."""
        if cls._instance is None:
            cls._instance = cls.load()
        return cls._instance

    @classmethod
    def _default_data_path(cls) -> Path:
        # Resolve via importlib.resources so the install layout matches the source layout.
        return Path(str(files("vardene").joinpath("data", cls._DEFAULT_FILENAME)))

    # --- lookups --------------------------------------------------------

    def by_lv(self, attribute: str) -> TagAttribute | None:
        return self._by_lv.get(attribute)

    def attributes_for_pos(self, part_of_speech: str) -> tuple[TagAttribute, ...]:
        return tuple(self._pos_to_attrs.get(part_of_speech, ()))
