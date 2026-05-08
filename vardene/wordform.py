"""Word + Wordform — Python port of `analyzer/Word.java` (354 LOC) and
`analyzer/Wordform.java` (229 LOC).

`Wordform` represents one possible morphological analysis of a token: a
specific lexeme + ending pair, with the surface attributes attached.
`Word` is the surface token plus all candidate Wordforms.
"""

from __future__ import annotations

from collections.abc import Iterable

from vardene.attributes import AttributeValues
from vardene.paradigm import Ending


class Wordform(AttributeValues):
    """A single morphological reading of a token."""

    __slots__ = ("ending", "lexeme", "token")

    def __init__(
        self,
        token: str,
        lexeme=None,  # type: ignore[no-untyped-def] - avoids Lexicon import cycle
        ending: Ending | None = None,
        attributes: AttributeValues | None = None,
    ) -> None:
        super().__init__(attributes)
        self.token: str = token
        self.lexeme = lexeme
        self.ending: Ending | None = ending
        # Inherit lexeme + ending attributes when constructing
        if lexeme is not None:
            self.add_all(lexeme.merged_attributes)
        if ending is not None:
            self.add_all(ending.attributes)

    def set_token(self, token: str) -> None:
        self.token = token

    def __repr__(self) -> str:
        attrs = ", ".join(f"{k}={v!r}" for k, v in self) if len(self) else ""
        return f"Wordform({self.token!r}, {attrs})"


class Word:
    """A surface token together with all candidate Wordform analyses."""

    __slots__ = ("_correct_wordform", "token", "wordforms")

    def __init__(self, token: str) -> None:
        self.token: str = token
        self.wordforms: list[Wordform] = []
        self._correct_wordform: Wordform | None = None

    def add_wordform(self, wf: Wordform) -> None:
        self.wordforms.append(wf)

    def is_recognized(self) -> bool:
        return bool(self.wordforms)

    def wordforms_count(self) -> int:
        return len(self.wordforms)

    def filter_by_attributes(self, attrs: AttributeValues) -> None:
        """Drop wordforms that don't weakly match every attribute in `attrs`."""
        self.wordforms = [wf for wf in self.wordforms if wf.is_matching_weak(attrs)]

    def best_wordform(self) -> Wordform | None:
        if self._correct_wordform is not None:
            return self._correct_wordform
        return self.wordforms[0] if self.wordforms else None

    def set_correct_wordform(self, wf: Wordform) -> None:
        self._correct_wordform = wf

    def get_correct_wordform(self) -> Wordform | None:
        return self._correct_wordform

    def add_attribute(self, attribute: str, value: str) -> None:
        """Add an attribute to every wordform."""
        for wf in self.wordforms:
            wf.add(attribute, value)

    def __repr__(self) -> str:
        return f"Word({self.token!r}, {len(self.wordforms)} analyses)"

    def __iter__(self) -> Iterable[Wordform]:
        return iter(self.wordforms)
