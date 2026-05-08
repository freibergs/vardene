"""AllEndings — Python port of `analyzer/AllEndings.java` (115 LOC).

A suffix trie keyed on the reversed ending strings. Given a word, walks back
from the end and returns every ending whose surface form is a suffix of the
word — this is the analyzer's first lookup step before running mija/lexeme
matching.

The Java implementation propagates endings down to all descendants in
`populate()` so that any node accumulates all endings whose suffix-prefix
matches the path so far. Lookup walks back from the word's last char and
stops when no child matches; the deepest visited node holds the answer.
"""

from __future__ import annotations

from collections.abc import Iterable

from vardene.paradigm import Ending


class _Node:
    __slots__ = ("endings", "first_child", "next_sibling", "symbol")

    def __init__(self, symbol: str) -> None:
        self.symbol: str = symbol
        self.first_child: _Node | None = None
        self.next_sibling: _Node | None = None
        self.endings: list[Ending] = []


class AllEndings:
    """Suffix-trie index from any prefix-of-an-ending → list of matching endings."""

    __slots__ = ("_by_id", "_endings", "_root")

    def __init__(self, endings: Iterable[Ending]) -> None:
        self._root = _Node(" ")
        self._endings: list[Ending] = list(endings)
        for e in self._endings:
            self._add(e)
        # Propagate accumulated endings down to all descendants.
        self._populate(self._root, [])
        self._by_id: dict[int, Ending] = {e.id: e for e in self._endings}

    def matched_endings(self, word: str) -> list[Ending]:
        """Return all endings that are suffixes of `word` (or prefixes thereof)."""
        i = len(word)
        t = self._root
        p = self._root
        while i > 1:
            p = t
            t = t.first_child
            while t is not None:
                if t.symbol == word[i - 1]:
                    break
                t = t.next_sibling
            if t is None:
                break
            i -= 1
        return p.endings

    def ending_by_id(self, ending_id: int) -> Ending | None:
        return self._by_id.get(ending_id)

    def _add(self, ending: Ending) -> None:
        s = ending.ending
        i = len(s)
        t = self._root
        p: _Node = self._root
        while i > 0:
            p = t
            t = t.first_child
            while t is not None and t.symbol != s[i - 1]:
                t = t.next_sibling
            if t is None:
                t = _Node(s[i - 1])
                t.next_sibling = p.first_child
                p.first_child = t
            i -= 1
        t.endings.append(ending)

    def _populate(self, node: _Node, parent_endings: list[Ending]) -> None:
        node.endings.extend(parent_endings)
        if node.first_child is not None:
            self._populate(node.first_child, list(node.endings))
        if node.next_sibling is not None:
            self._populate(node.next_sibling, parent_endings)
