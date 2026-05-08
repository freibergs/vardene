# Examples

Runnable cookbook recipes for [Vārdene](../README.md). Each script is self-contained and accepts a CLI argument so you can try your own input.

| Script | Demonstrates | Backing API endpoint |
|---|---|---|
| [`01_analyse_a_word.py`](01_analyse_a_word.py) | Single-word morphological analysis with full attribute set | `/api/analyze/<word>` |
| [`02_tag_a_sentence.py`](02_tag_a_sentence.py) | FSA-driven tokenisation + CRF + Viterbi disambiguation | `/api/morphotagger/<query>` |
| [`03_inflect_phrase.py`](03_inflect_phrase.py) | Multi-word phrase declension, normalisation, and personal-name paradigms | `/api/inflect_phrase`, `/api/normalize_phrase`, `/api/inflect_people/json` |

Run any of them directly:

```bash
python examples/01_analyse_a_word.py rakstu
python examples/02_tag_a_sentence.py "Māte sēd uz galda, vai ne?"
python examples/03_inflect_phrase.py "sarkanā māja"
python examples/03_inflect_phrase.py "Jānis Bērziņš" --names
python examples/03_inflect_phrase.py "Anna Liepa" --category person
```

Each script's docstring explains what it shows and which engine path it uses. They're meant to be read top-to-bottom as a tour of the library.
