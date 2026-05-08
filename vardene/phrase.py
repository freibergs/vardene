"""Multi-word phrase + personal-name inflection.

Wraps the single-word `Inflector` to handle short noun-phrase cases that
api.tezaurs.lv exposes via `/inflect_phrase`, `/normalize_phrase`, and
`/inflect_people/json`.

Algorithm:
  1. Tokenize the phrase via `vardene.splitting.tokenize`.
  2. Analyse each non-punctuation token; pick the best reading.
  3. Locate the head — rightmost noun or proper noun (or last token if none
     exists, e.g. a participle-only phrase).
  4. For each target Locījums in {Nominatīvs, Ģenitīvs, Datīvs, Akuzatīvs,
     Lokatīvs, Vokatīvs}, inflect the head to that case (preserving its
     Skaitlis); for the remaining tokens, inflect to the same case + the
     head's Skaitlis + Dzimte (if their POS supports gender agreement).
  5. Glue the surface forms together with the original whitespace.

This is sufficient for the canonical cases (Adj-N, ProperN-ProperN,
multi-word toponym), which is what the Java service handles. Edge cases
that require a real syntactic parser (genitive-modifier chains, apposition,
prepositions inside the phrase) fall back to per-word independent
inflection — same heuristic as the Java service.
"""

from __future__ import annotations

from collections.abc import Iterable

from vardene.analyzer import Analyzer
from vardene.attributes import AttributeValues
from vardene.inflector import Inflector
from vardene.splitting import tokenize as _tokenize
from vardene.wordform import Wordform

CASES_NO_VOC = (
    "Nominatīvs",
    "Ģenitīvs",
    "Datīvs",
    "Akuzatīvs",
    "Lokatīvs",
)
CASES_ALL = (*CASES_NO_VOC, "Vokatīvs")

_AGREE_POS = {"Lietvārds", "Īpašības vārds", "Skaitļa vārds", "Vietniekvārds"}


def _is_punct(tok: str) -> bool:
    return all(not c.isalnum() for c in tok) and tok != ""


def _is_head_candidate(wf: Wordform) -> bool:
    pos = wf.get("Vārdšķira")
    return pos == "Lietvārds"


def _best_reading(analyzer: Analyzer, token: str) -> Wordform | None:
    word = analyzer.analyze(token)
    if not word.wordforms:
        return None
    return word.wordforms[0]


def _pick_head(wfs: list[Wordform | None]) -> int:
    """Index of the head token. Rightmost noun, else rightmost analysed token,
    else last index."""
    for i in range(len(wfs) - 1, -1, -1):
        if wfs[i] is not None and _is_head_candidate(wfs[i]):
            return i
    for i in range(len(wfs) - 1, -1, -1):
        if wfs[i] is not None:
            return i
    return len(wfs) - 1


def _inflect_to(
    inflector: Inflector,
    token: str,
    reading: Wordform | None,
    target_case: str,
    head_number: str | None,
    head_gender: str | None,
    *,
    is_head: bool,
    force_head_number: bool = False,
) -> str:
    """Best surface form of `token` at `target_case`, agreeing with head."""
    if reading is None or reading.lexeme is None:
        return token

    pos = reading.get("Vārdšķira")
    forms = inflector.inflect_lexeme(reading.lexeme, reading.lexeme.lemma)
    if not forms:
        return token

    own_number = reading.get("Skaitlis")
    own_gender = reading.get("Dzimte")
    own_definiteness = reading.get("Noteiktība")

    if is_head and not force_head_number:
        target_number = own_number
    else:
        target_number = head_number or own_number
    target_gender = own_gender if pos == "Lietvārds" else (head_gender or own_gender)

    def _score(wf: Wordform) -> tuple[int, int, int, int]:
        s_case = 1 if wf.get("Locījums") == target_case else 0
        s_num = 1 if (target_number is None or wf.get("Skaitlis") == target_number) else 0
        s_gen = 1 if (target_gender is None or wf.get("Dzimte") == target_gender) else 0
        s_def = (
            1
            if (own_definiteness is None or wf.get("Noteiktība") == own_definiteness)
            else 0
        )
        return (s_case, s_num, s_gen, s_def)

    candidates = [wf for wf in forms if wf.get("Locījums") == target_case]
    if not candidates:
        return token
    candidates.sort(key=_score, reverse=True)
    return candidates[0].token


def inflect_phrase(
    phrase: str,
    *,
    analyzer: Analyzer | None = None,
    inflector: Inflector | None = None,
) -> dict[str, str]:
    """Return dict of {Locījums: inflected_phrase}."""
    if analyzer is None:
        analyzer = Analyzer()
    if inflector is None:
        inflector = Inflector(lexicon=analyzer.lexicon)

    tokens = _tokenize(phrase)
    if not tokens:
        return {}

    readings: list[Wordform | None] = []
    for tok in tokens:
        if _is_punct(tok):
            readings.append(None)
        else:
            readings.append(_best_reading(analyzer, tok))

    head_idx = _pick_head(readings)
    head_wf = readings[head_idx]
    head_number = head_wf.get("Skaitlis") if head_wf else None
    head_gender = head_wf.get("Dzimte") if head_wf else None

    result: dict[str, str] = {}
    for case in CASES_NO_VOC:
        out_tokens: list[str] = []
        for i, (tok, reading) in enumerate(zip(tokens, readings, strict=True)):
            if reading is None:
                out_tokens.append(tok)
                continue
            inflected = _inflect_to(
                inflector,
                tok,
                reading,
                case,
                head_number=head_number,
                head_gender=head_gender,
                is_head=(i == head_idx),
            )
            out_tokens.append(inflected)
        result[case] = _glue(tokens, out_tokens)
    return result


def normalize_phrase(
    phrase: str,
    *,
    analyzer: Analyzer | None = None,
    inflector: Inflector | None = None,
) -> str:
    """Lemmatised (Nominatīvs Vienskaitlis) form of `phrase`."""
    if analyzer is None:
        analyzer = Analyzer()
    if inflector is None:
        inflector = Inflector(lexicon=analyzer.lexicon)

    tokens = _tokenize(phrase)
    if not tokens:
        return ""

    readings: list[Wordform | None] = []
    for tok in tokens:
        if _is_punct(tok):
            readings.append(None)
        else:
            readings.append(_best_reading(analyzer, tok))

    head_idx = _pick_head(readings)
    head_wf = readings[head_idx]
    # Default: head Vienskaitlis (unless it's plurare-tantum / pluralia)
    head_number = "Vienskaitlis"
    if head_wf is not None and head_wf.is_matching_strong("Skaitlis 2", "Daudzskaitlinieks"):
        head_number = "Daudzskaitlis"
    head_gender = head_wf.get("Dzimte") if head_wf else None

    out_tokens: list[str] = []
    for i, (tok, reading) in enumerate(zip(tokens, readings, strict=True)):
        if reading is None:
            out_tokens.append(tok)
            continue
        out_tokens.append(
            _inflect_to(
                inflector,
                tok,
                reading,
                "Nominatīvs",
                head_number=head_number,
                head_gender=head_gender,
                is_head=(i == head_idx),
                force_head_number=True,  # normalisation: force head to its lemma number
            )
        )
    return _glue(tokens, out_tokens)


def inflect_people(
    name: str,
    *,
    analyzer: Analyzer | None = None,
    inflector: Inflector | None = None,
) -> list[list[dict[str, str]]]:
    """For a personal name, return a list-per-component of all 12 forms
    (6 cases × 2 numbers).

    Output mirrors api.tezaurs.lv `/inflect_people/json/<name>`: a JSON
    array of arrays. Each inner array is one name component (e.g. given
    name + surname), with 12 dicts inside listing every Skaitlis × Locījums
    form."""
    if analyzer is None:
        analyzer = Analyzer()
    if inflector is None:
        inflector = Inflector(lexicon=analyzer.lexicon)

    parts = [t for t in _tokenize(name) if not _is_punct(t)]
    out: list[list[dict[str, str]]] = []
    for part in parts:
        out.append(_person_part_forms(analyzer, inflector, part))
    return out


def _person_part_forms(
    analyzer: Analyzer, inflector: Inflector, surface: str
) -> list[dict[str, str]]:
    """All 12 forms of one personal-name component."""
    word = analyzer.analyze(surface)
    reading: Wordform | None = None
    for wf in word.wordforms:
        if (
            wf.is_matching_strong("Vārdšķira", "Lietvārds")
            and wf.is_matching_strong("Lietvārda tips", "Īpašvārds")
        ):
            reading = wf
            break
    if reading is None and word.wordforms:
        reading = word.wordforms[0]
    if reading is None or reading.lexeme is None:
        return [{"Vārds": surface, "Locījums": "Nominatīvs", "Skaitlis": "Vienskaitlis"}]

    forms = inflector.inflect_lexeme(reading.lexeme, reading.lexeme.lemma)
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for number in ("Vienskaitlis", "Daudzskaitlis"):
        for case in CASES_ALL:
            picks = [
                wf
                for wf in forms
                if wf.get("Locījums") == case and wf.get("Skaitlis") == number
            ]
            if not picks:
                continue
            wf = picks[0]
            key = (number, case)
            if key in seen:
                continue
            seen.add(key)
            entry: dict[str, str] = {
                "Vārds": wf.token,
                "Locījums": case,
                "Skaitlis": number,
            }
            for attr in ("Dzimte", "Deklinācija"):
                v = wf.get(attr)
                if v:
                    entry[attr] = v
            out.append(entry)
    return out


def _glue(original_tokens: list[str], new_tokens: list[str]) -> str:
    """Re-glue `new_tokens` with single spaces between alphanumerics, no space
    before punctuation. Token positions match `original_tokens`."""
    out_chars: list[str] = []
    for i, (orig, new) in enumerate(zip(original_tokens, new_tokens, strict=True)):
        if i > 0 and not _is_punct(orig):
            out_chars.append(" ")
        out_chars.append(new)
    return "".join(out_chars)


__all__ = [
    "CASES_ALL",
    "CASES_NO_VOC",
    "inflect_people",
    "inflect_phrase",
    "normalize_phrase",
]
