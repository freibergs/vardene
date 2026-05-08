"""Inflector — generation direction. Port of `Analyzer.generateInflections*` (~370 LOC).

Given a lemma (or a specific Lexeme), produces all surface forms by iterating
the paradigm's endings and applying `mija_for_inflection` to compose stems.

The Java code mixes generation with hardcoded form overrides, negation
expansion, and validation filters. This MVP covers the core path:
  - Iterate `paradigm.endings` for the lexeme's paradigm
  - Apply `mija_for_inflection(stem, ending.mija, third_stem, ...)` per ending
  - Build a `Wordform` for each (variant × ending) pair
  - Filter via `Ģenerēt=Nē` flag and singularia/pluralia tantum constraints
"""

from __future__ import annotations

from collections.abc import Iterable

from tezaurs.attributes import AttributeValues
from tezaurs.lexicon import Lexeme, Lexicon
from tezaurs.mijas import mija_for_inflection
from tezaurs.paradigm import Ending, Paradigm, ParadigmCatalog, StemType
from tezaurs.wordform import Wordform


class Inflector:
    """Generates all inflected forms for a lemma."""

    def __init__(self, lexicon: Lexicon | None = None) -> None:
        self.lexicon: Lexicon = lexicon if lexicon is not None else Lexicon.instance()
        self.paradigms: ParadigmCatalog = self.lexicon.paradigms

    def inflect(
        self,
        lemma: str,
        nouns_only: bool = False,
        attribute_filter: AttributeValues | None = None,
    ) -> list[Wordform]:
        """All surface forms across every Lexeme matching `lemma`."""
        results: list[Wordform] = []
        for lexeme in self.lexicon.lexemes_by_lemma(lemma):
            results.extend(self.inflect_lexeme(lexeme, lemma))
        if nouns_only:
            results = [w for w in results if w.is_matching_strong("Vārdšķira", "Lietvārds")]
        if attribute_filter is not None:
            results = [w for w in results if w.is_matching_weak(attribute_filter)]
        return results

    def inflect_from_paradigm(
        self,
        lemma: str,
        paradigm_name: str,
        attributes: AttributeValues | None = None,
    ) -> list[Wordform]:
        """Inflect `lemma` against a specific paradigm (e.g. for words not in the lexicon)."""
        paradigm = self.paradigms.by_name(paradigm_name)
        if paradigm is None:
            return self.inflect(lemma)
        if paradigm.stems > 1:
            # 1st-conjugation verbs need stem2/stem3 — fall back to lexicon lookup
            return self.inflect(lemma)
        ending = paradigm.lemma_ending()
        if ending is None or not lemma.endswith(ending.ending):
            return []
        # Strip the ending to get the base stem
        stem = lemma[: len(lemma) - len(ending.ending)] if ending.ending else lemma
        lexeme = Lexeme(
            lexeme_id=None,
            entry_id=None,
            human_id=None,
            lemma=lemma,
            stems={StemType.BASE: stem},
            paradigm=paradigm,
            own_attributes=attributes if attributes is not None else AttributeValues(),
            source="ad-hoc",
            language=paradigm.language,
        )
        return self.inflect_lexeme(lexeme, lemma)

    def inflect_lexeme(self, lexeme: Lexeme, lemma: str) -> list[Wordform]:
        """All surface forms of one Lexeme. Mirror of Java `generateInflections(Lexeme, String)`.

        For verbs (and only verbs), this method recursively expands negated
        forms by prepending the negation prefix (`ne` for LV, `na` for LTG)
        to both lemma and every stem before the mija step. The recursion adds
        `Noliegums=Jā` to the resulting Wordforms.
        """
        paradigm = lexeme.paradigm
        if paradigm is None:
            return []

        results = self._inflect_one(lexeme, lemma, negation=False)

        # For verbs, also generate negated forms (Java: generateInflections at line 1116-1119).
        is_verb = paradigm.own_attributes.is_matching_strong("Vārdšķira", "Darbības vārds")
        already_negated = lexeme.own_attributes.is_matching_strong("Noliegums", "Jā")
        if is_verb and not already_negated and lexeme.lemma:
            negation_prefix = self._negation_prefix(paradigm.language)
            negated_lemma = negation_prefix + lexeme.lemma
            results.extend(self._inflect_one(lexeme, negated_lemma, negation=True))
        return results

    def _inflect_one(self, lexeme: Lexeme, lemma: str, *, negation: bool) -> list[Wordform]:
        paradigm = lexeme.paradigm
        if paradigm is None:
            return []

        third_stem = lexeme.stems.get(StemType.PAST, "")
        proper_name = lexeme.own_attributes.is_matching_strong("Lietvārda tips", "Īpašvārds")
        lexeme_pos = lexeme.own_attributes.get("Vārdšķira") or paradigm.own_attributes.get("Vārdšķira")
        negation_prefix = self._negation_prefix(paradigm.language)
        if negation and third_stem:
            third_stem = negation_prefix + third_stem

        results: list[Wordform] = []
        for ending in paradigm.endings:
            ending_pos = ending.attributes.get("Vārdšķira")
            if ending_pos is not None and lexeme_pos is not None and ending_pos != lexeme_pos:
                continue

            stem_for_mija = lexeme.stems.get(ending.stem_type)
            if stem_for_mija is None:
                stem_for_mija = lexeme.stems.get(StemType.BASE)
            if stem_for_mija is None:
                continue
            if negation:
                stem_for_mija = negation_prefix + stem_for_mija

            add_superlative = (
                ending.attributes.is_matching_strong("Noteiktība", "Noteiktā")
                or ending.attributes.is_matching_strong("Vārdšķira", "Apstākļa vārds")
            )

            stem_variants = mija_for_inflection(
                stem_for_mija, ending.mija, third_stem, add_superlative, proper_name
            )

            for sv in stem_variants:
                surface = sv.celms + ending.ending
                surface = _recapitalize(surface, lemma)
                wf = Wordform(surface, lexeme=lexeme, ending=ending, attributes=sv)
                if negation:
                    wf.add("Noliegums", "Jā")
                    # Skip debitive forms in negation (Java line 1069-1072)
                    if wf.is_matching_strong("Izteiksme", "Vajadzības") or wf.is_matching_strong(
                        "Izteiksme", "Vajadzības, atstāstījuma paveids"
                    ):
                        continue
                if not _is_valid_form(wf, ending):
                    continue
                results.append(wf)
        return results

    def _negation_prefix(self, language: str) -> str:
        prefixes = self.paradigms.prefixes_for(language)
        if prefixes and prefixes.negation:
            return prefixes.negation[0]
        return "ne"


def _recapitalize(form: str, lemma: str) -> str:
    """Match `form` capitalization to `lemma` (proper-noun preservation)."""
    if not lemma or not form:
        return form
    if lemma[0].isupper():
        return form[:1].upper() + form[1:]
    return form


def _is_valid_form(wf: Wordform, ending: Ending) -> bool:
    """Filter: drop ending.do_not_generate forms and singularia/pluralia conflicts."""
    if ending.do_not_generate:
        return False
    if (
        wf.is_matching_strong("Skaitlis 2", "Vienskaitlinieks")
        and wf.is_matching_strong("Skaitlis", "Daudzskaitlis")
    ):
        return False
    if (
        wf.is_matching_strong("Skaitlis 2", "Daudzskaitlinieks")
        and wf.is_matching_strong("Skaitlis", "Vienskaitlis")
    ):
        return False
    return True


def all_inflections(lemma: str) -> Iterable[Wordform]:
    """Convenience: top-level singleton-ish inflector."""
    return Inflector().inflect(lemma)
