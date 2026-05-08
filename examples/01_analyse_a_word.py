"""Single-word analysis with full attribute set.

Run:
    python examples/01_analyse_a_word.py

Prints every candidate reading the engine produces for a Latvian word,
ordered by the additive Statistics ranking. The top reading is what
``analyzer.analyze(word).wordforms[0]`` would pick.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vardene.analyzer import Analyzer
from vardene.markup import to_tag

KEYS = ("Vārdšķira", "Skaitlis", "Dzimte", "Locījums", "Persona", "Laiks", "Izteiksme")


def main(word: str = "rakstu") -> None:
    analyzer = Analyzer()
    analyzer.enable_guessing = True

    result = analyzer.analyze(word)
    if not result.wordforms:
        print(f"No analysis for {word!r}")
        return

    print(f"{word!r} → {len(result.wordforms)} candidate reading(s):\n")
    for i, wf in enumerate(result.wordforms, 1):
        lemma = wf.lexeme.lemma if wf.lexeme else "?"
        attrs = "  ".join(f"{k}={wf.get(k)}" for k in KEYS if wf.get(k))
        print(f"  {i}. {wf.token}  ←  {lemma}  [{to_tag(wf)}]")
        print(f"     {attrs}\n")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "rakstu")
