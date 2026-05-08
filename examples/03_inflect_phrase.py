"""Multi-word noun-phrase declension table.

Run:
    python examples/03_inflect_phrase.py "sarkanā māja"
    python examples/03_inflect_phrase.py "Anna Liepa" --category person
    python examples/03_inflect_phrase.py "Jānis Bērziņš" --names

The phrase variant returns one inflected form per Locījums; the
``--names`` variant returns the full personal-name paradigm (6 cases ×
2 numbers per component).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vardene.analyzer import Analyzer
from vardene.inflector import Inflector
from vardene.phrase import inflect_people, inflect_phrase, normalize_phrase


def main(text: str, *, names: bool, category: str | None, gender: str | None) -> None:
    analyzer = Analyzer()
    analyzer.enable_guessing = True
    inflector = Inflector(lexicon=analyzer.lexicon)

    if names:
        components = inflect_people(text, analyzer=analyzer, inflector=inflector, gender=gender)
        for comp in components:
            head = comp[0]
            print(f"\n{head['Vārds']}  ({head.get('Dzimte', '?')}, decl. {head.get('Deklinācija', '?')})")
            for f in comp:
                print(f"  {f['Skaitlis']:14s} {f['Locījums']:10s} → {f['Vārds']}")
        return

    forms = inflect_phrase(text, analyzer=analyzer, inflector=inflector, category=category)
    norm = normalize_phrase(text, analyzer=analyzer, inflector=inflector)
    print(f"\nInflection of {text!r}:")
    for case in ("Nominatīvs", "Ģenitīvs", "Datīvs", "Akuzatīvs", "Lokatīvs"):
        print(f"  {case:<12s}: {forms.get(case, '—')}")
    if "Dzimte" in forms:
        print(f"  → detected gender: {forms['Dzimte']}")
    print(f"\nNormalised (lemma form): {norm}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="*", default=["sarkanā", "māja"])
    parser.add_argument("--category", choices=["person", "org", "loc"], default=None)
    parser.add_argument("--gender", choices=["m", "f"], default=None)
    parser.add_argument("--names", action="store_true",
                        help="treat input as a personal name (uses inflect_people)")
    args = parser.parse_args()
    main(" ".join(args.text), names=args.names, category=args.category, gender=args.gender)
