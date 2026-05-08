"""Valency-tag annotation helper — Python port of `VerbResource.java` +
`NonVerbResource.java` from `LUMII-AILab/Webservices`.

These back the upstream `/verbs/<query>` and `/neverbs/<query>` endpoints,
both used by the verb-valency annotation tool. Despite the name they do
*not* require an external valency database — they're pure morphology
heuristics over our existing engine: tokenize, pick the most likely
reading (with a +200 score bias toward or away from verbs), then emit a
small set of valency-relevant tags (`V1`/`V2`/`V3`/`Inf`,
`Nom`/`Gen`/`Dat`/`Acc`/`Loc`, `Adv`, plus `S`/`TR` for
sentence/transitive markers).
"""

from __future__ import annotations

from vardene.analyzer import Analyzer
from vardene.splitting import tokenize as _tokenize
from vardene.statistics import Statistics
from vardene.wordform import Wordform

_FALLBACK_TAGS: tuple[str, ...] = (
    "Nom", "Gen", "Dat", "Acc", "Loc",
    "V1", "V2", "V3", "Inf",
    "S", "TR", "Adv",
)

_CASE_TO_CODE: dict[str, str] = {
    "Nominatīvs": "Nom",
    "Ģenitīvs":   "Gen",
    "Datīvs":     "Dat",
    "Akuzatīvs":  "Acc",
    "Lokatīvs":   "Loc",
}


def _is_verb(wf: Wordform) -> bool:
    return wf.is_matching_strong("Vārdšķira", "Darbības vārds")


def _is_noun_or_pronoun(wf: Wordform) -> bool:
    return wf.is_matching_strong("Vārdšķira", "Lietvārds") or wf.is_matching_strong(
        "Vārdšķira", "Vietniekvārds"
    )


def _pick_best(word, prefer_verb: bool) -> Wordform | None:
    """Re-rank readings: Statistics.estimate + 200 if POS matches `prefer_verb`.
    Mirrors `VerbResource.tagWord` lines 56-67 of the Java source."""
    if not word.wordforms:
        return None
    stats = Statistics.instance()
    best = word.wordforms[0]
    best_score = float("-inf")
    for wf in word.wordforms:
        score = stats.estimate(wf)
        if _is_verb(wf) == prefer_verb:
            score += 200
        if score > best_score:
            best_score = score
            best = wf
    return best


def _tag_word(word, prefer_verb: bool) -> list[str]:
    """All valency tags for a single token. Order matches Java
    `LinkedHashSet` insertion order so the JSON output is reproducible."""
    tags: list[str] = []

    def _add(t: str) -> None:
        if t and t not in tags:
            tags.append(t)

    if word.wordforms:
        wf = _pick_best(word, prefer_verb)
        if wf is not None:
            if _is_verb(wf):
                person = wf.get("Persona")
                if person and len(person) == 1:
                    _add(f"V{person}")
                if wf.is_matching_strong("Izteiksme", "Nenoteiksme"):
                    _add("Inf")
                for t in ("V1", "V2", "V3", "Inf"):
                    _add(t)
            if _is_noun_or_pronoun(wf):
                case = _CASE_TO_CODE.get(wf.get("Locījums") or "")
                if case:
                    _add(case)
                for t in ("Nom", "Gen", "Dat", "Acc", "Loc"):
                    _add(t)
            if wf.is_matching_strong("Vārdšķira", "Apstākļa vārds"):
                _add("Adv")

    if not tags:
        return list(_FALLBACK_TAGS)
    return tags


def _tag_chunk(tokens: list, analyzer: Analyzer) -> list[str]:
    """Multi-word heuristics. Mirrors `VerbResource.tagChunk` (lines 92-117).
    If first token is a preposition, emit `{token}{caseCode}` per Rekcija.
    If first token is a conjunction, emit `S` (subordinate clause hint).
    Otherwise fall back to tagging the LAST token as non-verb."""
    if not tokens:
        return []
    first = tokens[0]
    tags: list[str] = []
    if first.wordforms:
        wf0 = first.wordforms[0]
        if wf0.is_matching_strong("Vārdšķira", "Prievārds"):
            for wf in first.wordforms:
                if not wf.is_matching_strong("Vārdšķira", "Prievārds"):
                    continue
                rekcija = wf.get("Rekcija")
                code = _CASE_TO_CODE.get(rekcija or "")
                if code:
                    tag = wf.token + code
                    if tag not in tags:
                        tags.append(tag)
        elif wf0.is_matching_strong("Vārdšķira", "Saiklis"):
            tags.append("S")

    if not tags:
        # "Ja nesapratām, dodam pēdējā vārda analīzi - Gunta teica, ka esot
        # ticamāk tā" — Java comment line 114.
        return _tag_word(tokens[-1], prefer_verb=False)
    return tags


def valency_tags(query: str, *, prefer_verb: bool, analyzer: Analyzer) -> list[str]:
    """Compute the valency-tag list for `query`. `prefer_verb=True` is
    `/verbs/<query>`; `prefer_verb=False` is `/neverbs/<query>`."""
    tokens_text = _tokenize(query)
    words = [analyzer.analyze(t) for t in tokens_text]
    if len(words) == 1:
        return _tag_word(words[0], prefer_verb=prefer_verb)
    return _tag_chunk(words, analyzer)


__all__ = ["valency_tags"]
