"""Variants — Python port of `analyzer/Variants.java` (44 LOC).

A small helper: `AttributeValues` plus a `celms` (stem) string. Used by
`mijas` to return candidate stems with associated grammatical features.
"""

from __future__ import annotations

from collections.abc import Mapping

from vardene.attributes import AttributeValues


class Variants(AttributeValues):
    """A stem candidate with optional grammatical attributes attached."""

    __slots__ = ("celms",)

    def __init__(
        self,
        celms: str,
        *kv: str,
        attributes: Mapping[str, str] | AttributeValues | None = None,
    ) -> None:
        """Construct from a stem and optional attribute key-value pairs.

        Mirrors Java's overloaded constructors:
          Variants(celms)
          Variants(celms, key, value)
          Variants(celms, key1, value1, key2, value2)
          Variants(celms, AttributeValues)
        """
        super().__init__(attributes)
        self.celms: str = celms
        if len(kv) % 2 != 0:
            raise TypeError("Variants kv args must come in (key, value) pairs")
        for i in range(0, len(kv), 2):
            self.add(kv[i], kv[i + 1])

    def __repr__(self) -> str:
        attrs = ", ".join(f"{k}={v!r}" for k, v in self) if len(self) else ""
        return f"Variants(celms={self.celms!r}{', ' + attrs if attrs else ''})"
