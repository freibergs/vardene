"""Tokenizer — Python port of `analyzer/Splitting.java`.

Drives the FSA branches in `vardene.trie.Trie` over a character stream to find
the longest legal token at each position, with one Latvian-specific quirk:
double apostrophes and trailing-period sentence boundaries are pre-marked
with U+200B (zero-width space) so the FSA breaks on them.

`tokenize(text)` returns a list of token strings, mirroring Java's
`Splitting.tokenize` minus the morpho-analysis (callers can analyse each
string with `Analyzer.analyze` if needed). `tokenize_sentences(text)` splits
a paragraph into sentences using the same rules as Java
`Splitting.tokenizeSentences`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from vardene.trie import Trie

DEFAULT_SENTENCE_LENGTH_CAP = 250

# Set lifted verbatim from Splitting.java line 46.
_SEPARATORS = (
    " \t\n\r  ​.?:/!,;\"'`´(){}<>«»-+[]"
    "—‐‑‒–―‘’‚‛“”„‟′″‴‵‶‷‹›‼‽⁈⁉․‥…&•*"
)

_TRAILING_PERIOD_RE = re.compile(r"([\w\d])\.(\s)*$")

# Sentence-final punctuation set (Java: zs tag = period, !, ?, ..., or combos).
# We don't morpho-analyse here, so we recognise by surface form.
_SENTENCE_CLOSERS = {".", "!", "?", "?!", "!?", "...", "…", "....", "....."}

_LAZY_TRIE: Trie | None = None


def _separator(c: str) -> bool:
    return c in _SEPARATORS


def _is_space(c: str) -> bool:
    if not c:
        return False
    return c.isspace() or c in (" ", "﻿", " ", "​")


def _build_master_trie() -> Trie:
    t = Trie()
    t.initialize_exceptions()
    return t


def _master_trie() -> Trie:
    global _LAZY_TRIE
    if _LAZY_TRIE is None:
        _LAZY_TRIE = _build_master_trie()
    return _LAZY_TRIE


def tokenize(text: str | None, *, brute_split: bool = False) -> list[str]:
    """Split `text` into surface tokens.

    `brute_split=True` falls back to whitespace-only splitting (matches
    `Splitting.tokenize(_, _, true)` in Java)."""
    if text is None:
        return []
    if brute_split:
        return [p for p in text.strip().split(" ") if p]

    automats = Trie(_master_trie())  # cloning ctor: shared branches, fresh cursor

    chunk = text + " "  # bug-fix from Java: append trailing space
    chunk = chunk.replace("''", "​''")
    chunk = _TRAILING_PERIOD_RE.sub(r"\1​.\2", chunk)

    tokens: list[str] = []

    in_word = False
    in_apostrophes = False
    progress = 0
    last_good_end = 0
    can_end_in_next = False

    def emit(start: int, end: int) -> None:
        slice_ = chunk[start:end]
        slice_ = slice_.replace("­", "")  # strip soft hyphen
        # Java appends a trailing space to `chunk` as a bug-fix sentinel, but
        # automata like n6_spaced ("a t s t...") consume it and emit a token
        # ending in space. Strip trailing whitespace before recording.
        slice_ = slice_.rstrip()
        if slice_:
            tokens.append(slice_)

    i = 0
    n = len(chunk)
    while i < n:
        c = chunk[i]
        if not in_word:
            if not _is_space(c):
                if c == "'":
                    in_apostrophes = True
                automats.reset()
                automats.find_next_branch(c)
                if automats.status() > 0:
                    in_word = True
                    progress = i
                    last_good_end = 0
                    can_end_in_next = automats.status() == 2
                else:
                    emit(i, i + 1)
            i += 1
            continue

        # in_word
        if can_end_in_next and (
            _separator(c) or not (i > 0 and chunk[i - 1].isalpha())
        ):
            last_good_end = i
            if c == "'" and in_apostrophes:
                emit(progress, i)
                emit(i, i + 1)
                in_apostrophes = False
                in_word = False
                i += 1
                continue
        can_end_in_next = False

        if automats.find_next(c) > 0:
            if automats.status() == 2:
                can_end_in_next = True
            i += 1
        else:
            if last_good_end > progress:
                emit(progress, last_good_end)
                i = last_good_end
                in_word = False
            else:
                # Try the next branch from `progress` rewound.
                i = progress
                automats.next_branch()
                automats.find_next_branch(chunk[i])
                if automats.status() > 0:
                    if automats.status() == 2:
                        can_end_in_next = True
                    i += 1
                else:
                    # Single-char fallback (Java FIXME path).
                    emit(i, i + 1)
                    in_word = False
                    i += 1

    if in_word:
        emit(progress, n)

    return tokens


def is_chunk_closer(token: str) -> bool:
    """Mirror of Splitting.isChunkCloser using surface form (we don't have the
    Word.attribute(zs) tag here — the user is post-tokenization)."""
    return token in _SENTENCE_CLOSERS


def tokenize_sentences(
    text: str | None,
    *,
    length_cap: int = DEFAULT_SENTENCE_LENGTH_CAP,
) -> list[list[str]]:
    """Split `text` into a list of sentences (each a list of tokens).

    Implements the same heuristic as `Splitting.tokenizeSentences`:
      - sentence boundary on punctuation token (`.`, `!`, `?`, `…`, ...)
      - hard cap at `length_cap` tokens per sentence
      - leading `"` or `)` after a closer is glued to the previous sentence
        (direct-speech quote handling)
    """
    if text is None:
        return []
    tokens = tokenize(text)
    sentences: list[list[str]] = []
    current: list[str] = []
    closers = {".", "!", "?", "\""}

    for tok in tokens:
        if not current:
            # Direct-speech: closing `"` or `)` after a sentence-final mark
            # belongs to the previous sentence.
            if (tok == "\"" or tok == ")") and sentences and sentences[-1]:
                prev = sentences[-1][-1]
                if prev in closers:
                    sentences[-1].append(tok)
                    continue

        current.append(tok)
        if (
            is_chunk_closer(tok)
            or len(current) > length_cap
        ):
            sentences.append(current)
            current = []

    if current:
        sentences.append(current)
    return sentences


__all__ = [
    "DEFAULT_SENTENCE_LENGTH_CAP",
    "is_chunk_closer",
    "tokenize",
    "tokenize_sentences",
]
