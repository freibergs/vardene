"""Trie / FSA — Python port of `analyzer/Trie.java` (564 LOC).

Despite the name, this is NOT a classical prefix trie. It's a collection of
finite-state automata that recognize special token shapes during tokenization:
clocks (`14:30`), ISO dates (`2009-12-14`), house numbers (`12A`), paragraphs
(`1.2.3.4.`), numbers, emails, URLs, domains, repeating punctuation (`...`,
`?!?`), spaced words (`a t s t a r p e s`), and compound tokens.

Custom user exceptions are stored in a real prefix trie via `add_exception`,
finalized into the branch list when `initialize_exceptions` is called.

Iterator API (consumed by `Splitting`):
  reset() → set cursor at start of branch 0
  find_next(c) → advance one char; returns 0 (no match) | 1 (partial) | 2 (full)
  status() → current 0/1/2 status
  next_branch() → move cursor to the next automaton; returns False at end
  find_next_branch(c) → advance through branches until one accepts c
  match(seq) → True iff seq is a complete match of any branch

The Java code uses `firstChild` / `nextSibling` to build a directed graph;
each node accepts a class of characters via `contains(c)`. Nodes are reused
via cycles (e.g. a digit-loop has `firstChild = self`).
"""

from __future__ import annotations


class Node:
    """Base FSA node. `first_child` advances on accepting char; `next_sibling`
    is the alternative at the current position. Cycles are allowed (e.g. a
    digit loop)."""

    __slots__ = ("automaton_name", "can_end", "first_child", "next_sibling")

    def __init__(self) -> None:
        self.first_child: Node | None = None
        self.next_sibling: Node | None = None
        self.can_end: bool = False
        self.automaton_name: str = ""

    def contains(self, c: str) -> bool:
        return False

    def set_automaton_name(self, name: str, _seen: set[int] | None = None) -> None:
        # Cycles in the graph (e.g. n5_punctuation root.firstChild=root) require
        # a visited set, otherwise we recurse forever.
        if _seen is None:
            _seen = set()
        if id(self) in _seen:
            return
        _seen.add(id(self))
        if name.casefold() == self.automaton_name.casefold():
            return
        self.automaton_name = name
        if self.first_child is not None:
            self.first_child.set_automaton_name(name, _seen)
        if self.next_sibling is not None:
            self.next_sibling.set_automaton_name(name, _seen)


class StringNode(Node):
    """Accepts any character contained in `symbol` (which doubles as both the
    lower and upper case set, e.g. `"hH"`)."""

    __slots__ = ("symbol",)

    def __init__(self, symbol: str) -> None:
        super().__init__()
        self.symbol: str = symbol

    def contains(self, c: str) -> bool:
        return c in self.symbol


class UCNode(Node):
    """Any uppercase letter."""

    __slots__ = ()

    def contains(self, c: str) -> bool:
        return c.isupper()


class LCNode(Node):
    """Any lowercase letter."""

    __slots__ = ()

    def contains(self, c: str) -> bool:
        return c.islower()


class LetterNode(Node):
    """Any letter (or soft hyphen U+00AD, which `Splitting` strips later)."""

    __slots__ = ()

    def contains(self, c: str) -> bool:
        return c.isalpha() or c == "­"


class DigitNode(Node):
    """Any decimal digit."""

    __slots__ = ()

    def contains(self, c: str) -> bool:
        return c.isdigit()


class LetterOrDigitNode(Node):
    """Any letter, digit, soft hyphen, or character from the explicit `symbol` set."""

    __slots__ = ("symbol",)

    def __init__(self, symbol: str = "") -> None:
        super().__init__()
        self.symbol: str = symbol

    def contains(self, c: str) -> bool:
        return c.isalnum() or c == "­" or c in self.symbol


# ---------------------------------------------------------------------------
# Special-token automata. Each builds an isolated FSA rooted at the returned node.
# ---------------------------------------------------------------------------


def n1_dz_initials() -> Node:
    """`Dz.`, `Dž.`, or any uppercase-letter followed by `.` — initials."""
    root = StringNode("D")
    root.first_child = StringNode("zžZŽ")
    root.first_child.next_sibling = StringNode(".")
    root.first_child.next_sibling.can_end = True
    root.first_child.first_child = root.first_child.next_sibling
    root.next_sibling = UCNode()
    root.next_sibling.first_child = root.first_child.next_sibling
    root.set_automaton_name("n1 - Dz Dž UpperCaseLetter")
    return root


def n2_a_clock() -> Node:
    """Clock times: `[01]?\\d:[0-5]\\d` or `2[0-3]:[0-5]\\d`."""
    root = StringNode("01")
    root.first_child = DigitNode()
    root.first_child.first_child = StringNode(":")
    root.first_child.first_child.first_child = StringNode("012345")
    root.first_child.first_child.first_child.first_child = DigitNode()
    root.first_child.first_child.first_child.first_child.can_end = True
    root.first_child.first_child.first_child.first_child.first_child = root.first_child.first_child
    root.next_sibling = StringNode("2")
    root.next_sibling.first_child = StringNode("0123")
    root.next_sibling.first_child.first_child = root.first_child.first_child
    root.set_automaton_name("n2a - pulkstenis")
    return root


def n2_aa_date() -> Node:
    """ISO dates: `\\d{4}[-.]\\d{2}[-.]\\d{2}\\.?`."""
    root = DigitNode()
    root.first_child = DigitNode()
    root.first_child.first_child = DigitNode()
    root.first_child.first_child.first_child = DigitNode()
    root.first_child.first_child.first_child.first_child = StringNode("-.")
    r2 = root.first_child.first_child.first_child.first_child
    r2.first_child = DigitNode()
    r2.first_child.first_child = DigitNode()
    r2.first_child.first_child.first_child = StringNode("-.")
    r2 = r2.first_child.first_child.first_child
    r2.first_child = DigitNode()
    r2.first_child.first_child = DigitNode()
    r2.first_child.first_child.can_end = True
    r2.first_child.first_child.first_child = StringNode(".")
    r2.first_child.first_child.first_child.can_end = True
    root.set_automaton_name("n2aa - datums")
    return root


def n2_aaa_houses() -> Node:
    """House numbers: `\\d+[A-Z]`."""
    root = DigitNode()
    root.first_child = DigitNode()
    root.first_child.first_child = root.first_child
    root.first_child.next_sibling = LetterNode()
    root.first_child.next_sibling.can_end = True
    root.set_automaton_name("n1 - māju numuri")  # name kept identical to Java
    return root


def n2_b_numbers() -> Node:
    """Numbers in many shapes: integers, ordinals, decimals, thousands separators,
    fractions, money form `123,-`."""
    root = DigitNode()
    root.can_end = True
    root.first_child = DigitNode()
    root.first_child.can_end = True
    root.first_child.first_child = root.first_child

    thousands = StringNode(" '")
    thousands.first_child = DigitNode()
    thousands.first_child.first_child = DigitNode()
    ones = DigitNode()
    ones.can_end = True
    ones.first_child = thousands
    thousands.first_child.first_child.first_child = ones
    root.first_child.next_sibling = thousands

    after_decimal = DigitNode()
    after_decimal.can_end = True
    after_decimal.first_child = DigitNode()
    after_decimal.first_child.can_end = True
    after_decimal.first_child.first_child = after_decimal.first_child
    after_decimal.next_sibling = StringNode("-‐‑‒–—―'")
    after_decimal.next_sibling.can_end = True

    period = StringNode(".")
    period.can_end = True  # ordinals
    period.first_child = after_decimal
    thousands.next_sibling = period

    comma = StringNode(",")
    comma.first_child = after_decimal
    period.next_sibling = comma

    fractions = StringNode("/\\")
    fractions.first_child = DigitNode()
    fractions.first_child.first_child = fractions.first_child
    fractions.first_child.can_end = True
    comma.next_sibling = fractions

    root.set_automaton_name("n2b - skaitļi")
    return root


def n2_c_paragraphs() -> Node:
    """Paragraph numbers / IP addresses: `\\d+(\\.\\d+){0,3}\\.?`."""
    root = DigitNode()
    root.first_child = root
    root.next_sibling = StringNode(".")
    second = DigitNode()
    root.next_sibling.first_child = second
    second.first_child = second
    second.next_sibling = StringNode(".")
    second.next_sibling.can_end = True
    third = DigitNode()
    third.can_end = True
    second.next_sibling.first_child = third
    third.first_child = third
    third.next_sibling = StringNode(".")
    third.next_sibling.can_end = True
    third.next_sibling.first_child = third
    root.set_automaton_name("n2c - paragrāfu numuri")
    return root


def n3_email() -> Node:
    """Email: `[\\w]+([_\\-.][\\w]+)*@[\\w]+([_\\-.][\\w]+)*`."""
    root = LetterOrDigitNode()
    root.first_child = LetterOrDigitNode("_-.")
    root.first_child.first_child = root.first_child
    root.first_child.next_sibling = StringNode("@")
    root.first_child.next_sibling.first_child = LetterOrDigitNode()
    root.first_child.next_sibling.first_child.can_end = True
    root.first_child.next_sibling.first_child.first_child = (
        root.first_child.next_sibling.first_child
    )
    root.first_child.next_sibling.first_child.next_sibling = StringNode("_-.")
    root.first_child.next_sibling.first_child.next_sibling.first_child = (
        root.first_child.next_sibling.first_child
    )
    root.set_automaton_name("n3 - epasts")
    return root


def n4a_url() -> Node:
    """URLs starting with `http`/`https`/`ftp`/`www`."""
    root = StringNode("hH")
    root.first_child = StringNode("tT")
    root.first_child.first_child = StringNode("tT")
    root.first_child.first_child.first_child = StringNode("pP")
    root.first_child.first_child.first_child.first_child = StringNode(":")
    root.first_child.first_child.first_child.first_child.first_child = StringNode("/")
    root.first_child.first_child.first_child.first_child.first_child.first_child = StringNode("/")
    root.first_child.first_child.first_child.first_child.next_sibling = StringNode("sS")
    root.first_child.first_child.first_child.first_child.next_sibling.first_child = (
        root.first_child.first_child.first_child.first_child
    )
    root.next_sibling = StringNode("fF")
    root.next_sibling.first_child = StringNode("tT")
    root.next_sibling.first_child.first_child = StringNode("pP")
    root.next_sibling.first_child.first_child.first_child = (
        root.first_child.first_child.first_child.first_child
    )
    root.next_sibling.next_sibling = StringNode("wW")
    root.next_sibling.next_sibling.first_child = StringNode("wW")
    root.next_sibling.next_sibling.first_child.first_child = StringNode("wW")
    root.next_sibling.next_sibling.first_child.first_child.first_child = StringNode(".")
    root.next_sibling.next_sibling.first_child.first_child.first_child.first_child = (
        LetterOrDigitNode("/")
    )
    root.next_sibling.next_sibling.first_child.first_child.first_child.first_child.can_end = True
    # Stitch the http(s):// path onto the same body that www. uses
    root.first_child.first_child.first_child.first_child.first_child.first_child.first_child = (
        root.next_sibling.next_sibling.first_child.first_child.first_child.first_child
    )
    body = root.next_sibling.next_sibling.first_child.first_child.first_child.first_child
    body.first_child = LetterOrDigitNode("/")
    body.first_child.can_end = True
    body.first_child.first_child = body.first_child
    body.first_child.first_child.can_end = True
    body.first_child.first_child.next_sibling = StringNode("_-@:?=&%.")
    body.first_child.first_child.next_sibling.first_child = body
    root.set_automaton_name("n4a - URI")
    return root


def n4b_domain() -> Node:
    """Domain: 2+ letters, then `.lv` or `.LV`."""
    root = LetterNode()
    root.first_child = LetterNode()
    root.first_child.first_child = root.first_child  # 2+ letters
    root.first_child.next_sibling = StringNode(".")
    root.first_child.next_sibling.first_child = StringNode("lL")
    root.first_child.next_sibling.first_child.first_child = StringNode("vV")
    root.first_child.next_sibling.first_child.first_child.can_end = True
    root.set_automaton_name("n4a - domēnvārds")  # name kept identical to Java
    return root


def n5_punctuation() -> Node:
    """Repeating punctuation (`.`, `?`, `!`) — e.g. `?!?` or `…`."""
    root = StringNode(".?!")
    root.can_end = True
    root.first_child = root
    root.set_automaton_name("n5 - pieturzīmes")
    return root


def n6_spaced() -> Node:
    """Spaced-out words like `a t s t a r p e s`."""
    root = LetterNode()
    root.first_child = StringNode(" ")
    root.first_child.first_child = LetterNode()
    root.first_child.first_child.can_end = True
    root.first_child.first_child.first_child = root.first_child
    root.set_automaton_name("n6 - atstarpes")
    return root


def n7_compound() -> Node:
    """Compound tokens: alphanumerics with `_`/`-` only in the middle, `'` only at the end."""
    root = LetterOrDigitNode()
    root.can_end = True
    root.first_child = LetterOrDigitNode()
    root.first_child.can_end = True
    root.first_child.first_child = root.first_child
    root.first_child.next_sibling = StringNode("_-")
    root.first_child.next_sibling.first_child = root
    root.first_child.next_sibling.next_sibling = StringNode("'")
    root.first_child.next_sibling.next_sibling.can_end = True
    root.set_automaton_name("n7 - saliktie vārdi")
    return root


# ---------------------------------------------------------------------------
# Trie: holds the branch list and an iterator cursor.
# ---------------------------------------------------------------------------


class Trie:
    """Collection of automata + an iterator cursor.

    Status codes returned by `find_next` and `status`:
        0 — no match (cursor exhausted)
        1 — partial match (more chars accepted, but not yet a valid endpoint)
        2 — full match (current node is a valid endpoint; more chars may also work)
    """

    __slots__ = (
        "_branch_list",
        "_exception_root",
        "_is_first",
        "_iterator",
        "branch_iterator",
    )

    _BUILTIN_EXCEPTIONS: tuple[str, ...] = ("''", "’’", "‘’", "***")

    def __init__(self, source: Trie | None = None) -> None:
        if source is not None:
            # Cloning constructor: share the branch list, fresh iterator.
            self._branch_list: list[Node] = source._branch_list
            self._exception_root: Node | None = source._exception_root
            self.reset()
            return

        self._branch_list = []
        self._exception_root = Node()
        for s in self._BUILTIN_EXCEPTIONS:
            self._add(s, self._exception_root)
        self._iterator: Node | None = None
        self._is_first: bool = True
        self.branch_iterator: int = 0

    # --- prefix-trie style insertion (for exceptions) -------------------

    @staticmethod
    def _add(s: str, root: Node) -> None:
        """Insert `s` as a path of StringNode-s into the trie rooted at `root`.

        Each char becomes a StringNode containing both its lowercase and
        uppercase form (Java original behaviour).
        """
        node = root
        for ch in s:
            child = node.first_child
            prev = node
            while child is not None and not child.contains(ch):
                child = child.next_sibling
            if child is None:
                # Insert a new sibling at the head of the child list.
                new_node = StringNode(ch.lower() + ch.upper())
                new_node.next_sibling = prev.first_child
                prev.first_child = new_node
                node = new_node
            else:
                node = child
        node.can_end = True

    def add_exception(self, s: str) -> None:
        if self._exception_root is None:
            # Java silently ignores additions after finalization (see comment in
            # original): "Tēzaurs webserviss mēdz pielikt dīvainas pagaidu leksēmas".
            return
        self._add(s, self._exception_root)

    def initialize_exceptions(self) -> None:
        """Lock the exception trie and append all built-in automata.

        Order matters: paragraphs (n2c) are listed before numbers (n2b) so the
        number automaton doesn't greedily eat the paragraph form `1.2.3.4.`.
        """
        if self._exception_root is None:
            return
        if self._exception_root.first_child is not None:
            self._branch_list.append(self._exception_root.first_child)
        self._exception_root = None

        self._branch_list.append(n1_dz_initials())
        self._branch_list.append(n2_a_clock())
        self._branch_list.append(n2_aa_date())
        self._branch_list.append(n2_aaa_houses())
        self._branch_list.append(n2_c_paragraphs())  # before n2b on purpose
        self._branch_list.append(n2_b_numbers())
        self._branch_list.append(n3_email())
        self._branch_list.append(n4a_url())
        self._branch_list.append(n4b_domain())
        self._branch_list.append(n5_punctuation())
        self._branch_list.append(n6_spaced())
        self._branch_list.append(n7_compound())

    # --- iterator API ---------------------------------------------------

    def reset(self) -> None:
        self._is_first = True
        self.branch_iterator = 0
        self._iterator = self._branch_list[0] if self._branch_list else None

    def next_branch(self) -> bool:
        self._is_first = True
        self.branch_iterator += 1
        if self.branch_iterator < len(self._branch_list):
            self._iterator = self._branch_list[self.branch_iterator]
            return True
        self._iterator = None
        return False

    def find_next_branch(self, c: str) -> None:
        if self.branch_iterator >= len(self._branch_list):
            return
        while True:
            if self.find_next(c) > 0:
                return
            if not self.next_branch():
                return

    def find_next(self, c: str) -> int:
        if self._iterator is None:
            return 0
        if not self._is_first:
            self._iterator = self._iterator.first_child
        self._is_first = False
        while self._iterator is not None and not self._iterator.contains(c):
            self._iterator = self._iterator.next_sibling
        return self.status()

    def status(self) -> int:
        if self._iterator is None:
            return 0
        return 2 if self._iterator.can_end else 1

    def match(self, sequence: str) -> bool:
        """True iff `sequence` is fully accepted by any of the configured branches."""
        # The Java version walks ONE branch only — `findNext(c)` doesn't try
        # other branches when the current one rejects. We preserve that.
        self.reset()
        last_status = 0
        for c in sequence:
            last_status = self.find_next(c)
            if last_status == 0:
                return False
        return last_status == 2
