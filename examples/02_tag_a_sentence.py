"""Sentence-level disambiguation — what ``/api/morphotagger`` returns.

Run:
    python examples/02_tag_a_sentence.py "Māte sēd uz galda."

Tokenises the input via the FSA-driven Splitting port (lexicon-aware,
recognises clocks, URLs, dates, abbreviations like ``plkst.``) and
runs the full disambiguator stack — POS CRF, per-POS classifier,
tag-bigram Viterbi rescoring, per-form corpus overrides, plus the
Latvian preposition-agreement post-pass — to pick one reading per
token.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vardene.analyzer import Analyzer
from vardene.markup import to_tag
from vardene.splitting import tokenize


def main(text: str) -> None:
    analyzer = Analyzer()
    analyzer.enable_guessing = True

    tokens = tokenize(text)
    sentence = analyzer.analyze_sentence(tokens)

    width = max(len(t) for t in tokens)
    print(f"{'token':<{width}}  {'lemma':<14}  tag")
    print(f"{'-' * width}  {'-' * 14}  ---")
    for tok, word in zip(tokens, sentence, strict=True):
        if not word.wordforms:
            print(f"{tok:<{width}}  {'(no analysis)':<14}  --")
            continue
        wf = word.wordforms[0]
        lemma = wf.lexeme.lemma if wf.lexeme else "?"
        tag = to_tag(wf)
        print(f"{tok:<{width}}  {lemma:<14}  {tag}")


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Māte sēd uz galda, vai ne?"
    main(text)
