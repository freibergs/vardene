"""Analyzer — Python port of `analyzer/Analyzer.java` (1124 LOC).

This MVP covers the **core analysis path**:
  - Strip an ending from a word; apply backwards mija; check whether the
    residual stem is a known lexeme stem in that paradigm.
  - Verify each candidate via `verify_back_inflection` before accepting.
  - Filter rare/regional/outdated forms.

Not yet ported (TODO):
  - Prefix stripping for verbs (`enable_prefixes`)
  - Compound word search (`search_compound_words`)
  - Heuristic guessing for unknown words (`guessByEnding`, `guess_diminutive`,
    `guess_derived_noun`)
  - Hardcoded regex fallbacks for numbers, ordinals, abbreviations, URLs
  - Vocative form handling
  - Word cache (we just rely on Lexicon's lazy indexes)

The core path is enough to validate against `api.tezaurs.lv` for the bulk
of common nouns/verbs/adjectives.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from tezaurs.all_endings import AllEndings
from tezaurs.attributes import AttributeValues
from tezaurs.lexicon import Lexeme, Lexicon
from tezaurs.mijas import mija_variants, verify_back_inflection
from tezaurs.paradigm import Ending, ParadigmCatalog, StemType
from tezaurs.statistics import Statistics
from tezaurs.wordform import Word, Wordform


def _load_form_disambiguation() -> dict[str, tuple[str, str]]:
    """Load the trained form→(tag, lemma) table shipped in `data/`."""
    import json
    from importlib.resources import files

    path = Path(str(files("tezaurs").joinpath("data", "form_disambiguation.json")))
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {form: (tag, lemma) for form, (tag, lemma) in raw.items()}


def _load_verb_transitivity() -> dict[str, str]:
    """Load lemma→('t'/'i') overrides for verbs whose lexicon entry's
    transitivity disagrees with corpus usage in ≥80% of cases."""
    import json
    from importlib.resources import files

    path = Path(str(files("tezaurs").joinpath("data", "verb_transitivity.json")))
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


_VERB_TRANSITIVITY: dict[str, str] = _load_verb_transitivity()
_TRANS_LV = {"t": "Transitīvs", "i": "Intransitīvs"}


def _load_adverb_pakape() -> dict[str, str]:
    """Load adverb-lemma → Pakāpe overrides built from the gold corpus.
    Most adverbs (kad/jau/kā/tad/vēl/ļoti/...) consistently get Pakāpe=Nepiemīt
    even though the lexicon stamps them as Pamata."""
    import json
    from importlib.resources import files

    path = Path(str(files("tezaurs").joinpath("data", "adverb_pakape.json")))
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


_ADVERB_PAKAPE: dict[str, str] = _load_adverb_pakape()


def _load_verb_type() -> dict[str, str]:
    """Load lemma → 'Darbības vārda tips' overrides for modal/auxiliary
    verbs (varēt/spēt/vajadzēt/...) where lexicon's 'Patstāvīgs' disagrees
    with gold-corpus annotation."""
    import json
    from importlib.resources import files

    path = Path(str(files("tezaurs").joinpath("data", "verb_type.json")))
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


_VERB_TYPE: dict[str, str] = _load_verb_type()


def _load_form_strong_overrides() -> dict[str, tuple[str, str]]:
    """Load high-confidence per-form (tag, lemma) overrides.

    Each entry was seen ≥5 times in the training corpus with ≥85% concentration
    on a single (tag, lemma) pair. Applied AFTER sentence-level disambiguation
    as a final correction step — closes ~1.3pp of tag-accuracy gap on held-out
    data."""
    import json
    from importlib.resources import files

    path = Path(str(files("tezaurs").joinpath("data", "form_strong_overrides.json")))
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {form: (tag, lemma) for form, (tag, lemma) in raw.items()}


_FORM_STRONG_OVERRIDES: dict[str, tuple[str, str]] = _load_form_strong_overrides()


class Analyzer:
    """Morphological analyzer. Loads the lexicon + paradigms once, then
    `analyze(word)` produces all candidate `Wordform`s."""

    _LEXEME_CACHE_SIZE = 8192  # LRU cap on materialised Lexeme objects

    def __init__(self, lexicon: Lexicon | None = None) -> None:
        self.lexicon: Lexicon = lexicon if lexicon is not None else Lexicon.instance()
        self.paradigms: ParadigmCatalog = self.lexicon.paradigms

        # Build the suffix trie from every paradigm's endings.
        all_endings: list[Ending] = []
        for p in self.paradigms.paradigms:
            all_endings.extend(p.endings)
        self._all_endings = AllEndings(all_endings)

        # Per-(paradigm_id, language, stem_type) index: stem → list[row_idx].
        # Built lazily on first lookup. Stores integer row offsets only; the
        # corresponding Lexeme objects are materialised on demand in
        # `_materialize_lexeme` with an LRU cache. This keeps memory at
        # ~10 MB for the index instead of ~870 MB.
        self._stem_index: dict[
            tuple[int, str, StemType], dict[str, list[int]]
        ] = {}
        self._lexeme_cache: dict[tuple[int, int, str], Lexeme] = {}

        # Hardcoded-form index: surface form → list[Lexeme] for rows in the
        # `hardcoded` paradigm. These are irregular verbs (būt, iet, ...) and
        # pronouns where every form is enumerated explicitly. Indexed lazily.
        self._hardcoded_form_index: dict[str, list[Lexeme]] | None = None

        # Settings flags (mirror Java defaults).
        self.enable_prefixes: bool = True
        self.search_compound_words: bool = False
        self.enable_guessing: bool = False
        self.enable_diminutive: bool = True  # FIXME: not yet implemented
        self.enable_derived_nouns: bool = True  # FIXME: not yet implemented
        self.enable_vocative: bool = False
        self.remove_rare_words: bool = True
        self.remove_regional_words: bool = True
        # Statistical disambiguation (load lazily to avoid cold-start cost).
        self._statistics: Statistics | None = None
        self.disambiguate: bool = True
        # Trained form-disambiguation lookup (form → preferred (tag, lemma)).
        # Loaded lazily; absent if the data file isn't shipped.
        self._form_disambig: dict[str, tuple[str, str]] | None = None
        self.use_trained_disambig: bool = True
        # CRF-based sentence tagger (LVTagger MorphoCRF equivalent).
        self._crf_tagger = None  # CRFTagger | None
        self._crf_loaded = False
        self.use_crf_tagger: bool = True

    # --- analysis ------------------------------------------------------

    def analyze_sentence(self, words: list[str]) -> list[Word]:
        """Analyze every word in a sentence and apply CRF disambiguation across
        the whole sequence. This is where the LVTagger-style context features
        actually matter — `kas` mid-sentence resolves differently than `Kas?`
        starting a question.
        """
        # Skip single-word CRF during per-token analyze — we redo it sentence-
        # level below, and the single-word path is the dominant cost (≈80% of
        # runtime calls `predict_log_proba` for nothing useful).
        was_crf = self.use_crf_tagger
        self.use_crf_tagger = False
        try:
            results = [self.analyze(w) for w in words]
        finally:
            self.use_crf_tagger = was_crf
        # Mid-sentence capitalized tokens are almost always proper nouns. If
        # the lexicon only has common-noun readings (Vilks → ncmsn1), promote
        # an Īpašvārds variant so the CRF/classifier has something to pick.
        for idx, (word, result) in enumerate(zip(words, results, strict=True)):
            if idx == 0 or not word or not word[0].isupper():
                continue
            _add_proper_noun_reading(result, word)
        if self.use_crf_tagger:
            tagger = self._get_crf_tagger()
            if tagger is not None:
                tagger.tag_sentence(results)
        # Final per-form override pass — high-confidence (count≥5, ≥85%
        # concentration in train corpus) form→(tag, lemma) lookups override
        # the sentence-level pick. Synthesises a wordform from the target
        # tag when no candidate matches; otherwise promotes existing match.
        if _FORM_STRONG_OVERRIDES:
            for word, result in zip(words, results, strict=True):
                target = _FORM_STRONG_OVERRIDES.get(word)
                if target is None:
                    continue
                _apply_form_override(result, word, target[0], target[1])
        return results

    def _get_crf_tagger(self):
        if not self._crf_loaded:
            try:
                from tezaurs.crf_tagger import CRFTagger
                self._crf_tagger = CRFTagger.instance()
            except Exception:
                self._crf_tagger = None
            self._crf_loaded = True
        return self._crf_tagger

    def analyze(self, word: str) -> Word:
        """Analyze a single token. Returns a Word with all candidate Wordforms.

        Capitalization handling: if the input has any uppercase, we analyze
        the lowercase form and tag each result with the original case style.
        """
        word = word.strip()
        result = Word(word)
        if not word:
            return result

        was_capitalized = word != word.lower()
        if was_capitalized:
            lc = self._analyze_lowercase(word.lower(), word)
            for wf in lc.wordforms:
                wf.set_token(word)
                wf.add("Lielo burtu lietojums", _detect_case(word))
                result.add_wordform(wf)
        else:
            result = self._analyze_lowercase(word, word)

        # Final disambiguation pass with capitalization-aware preference.
        if result.is_recognized() and self.disambiguate:
            if self._statistics is None:
                self._statistics = Statistics.instance()
            result.wordforms = self._statistics.disambiguate(
                result.wordforms, prefer_proper=was_capitalized
            )

        # Single-word CRF POS filter: predict POS even without sentence context
        # (uses just BOS/EOS markers + suffixes). Works decently for unambiguous
        # words; sentence-level `analyze_sentence` is more accurate.
        if result.is_recognized() and self.use_crf_tagger and len(result.wordforms) > 1:
            tagger = self._get_crf_tagger()
            if tagger is not None:
                tagger.tag_word(result)

        # Trained form-disambiguation: if the surface form is in our learned
        # table and our analysis includes a wordform whose (tag, lemma) matches,
        # promote that wordform to the front. Conceptually equivalent to a
        # unigram CRF tagger trained on the same `train.txt` Java uses.
        if result.is_recognized() and self.use_trained_disambig:
            if self._form_disambig is None:
                self._form_disambig = _load_form_disambiguation()
            target = self._form_disambig.get(word)
            if target is not None:
                _promote_matching(result, target[0], target[1])
        return result

    def _analyze_lowercase(self, word: str, original: str) -> Word:
        result = Word(word)
        proper_name = _is_first_capitalized(original)

        # Hardcoded-form lookup first — this is where irregular verb forms
        # (`esmu`, `bija`, `iet`, ...) and pronoun forms live in the data.
        for lexeme in self._hardcoded_lexemes(word):
            wf = Wordform(word, lexeme=lexeme, ending=lexeme.paradigm.lemma_ending() if lexeme.paradigm else None)
            wf.add("Minējums", "Nav")
            if self._is_acceptable(wf):
                result.add_wordform(wf)

        for ending in self._all_endings.matched_endings(word):
            try:
                stem_with_mija = ending.stem(word)
            except Exception:  # WrongEndingError shouldn't happen for matched endings
                continue

            paradigm = ending.paradigm
            if paradigm is None:
                continue

            stem_variants = mija_variants(stem_with_mija, ending.mija, proper_name)
            for sv in stem_variants:
                lexemes = self._lexemes_with_stem(
                    paradigm.id, paradigm.language, sv.celms, ending.stem_type
                )
                found_direct = False
                if lexemes:
                    for lexeme in lexemes:
                        third_stem = lexeme.stems.get(StemType.PAST, stem_with_mija)
                        if not verify_back_inflection(
                            sv, stem_with_mija, ending.mija, third_stem, proper_name
                        ):
                            continue
                        wf = Wordform(word, lexeme=lexeme, ending=ending, attributes=sv)
                        wf.add("Minējums", "Nav")
                        if self._is_acceptable(wf):
                            result.add_wordform(wf)
                            found_direct = True
                if not found_direct:
                    if self.enable_diminutive:
                        self._guess_diminutive(word, result, ending, sv, original)
                    if self.enable_derived_nouns:
                        self._guess_derived_noun(word, result, ending, sv, original)

        # Preserve original capitalization for proper-noun lemmas.
        if proper_name and result.is_recognized():
            for wf in result.wordforms:
                if wf.is_matching_strong("Lietvārda tips", "Īpašvārds") and wf.lexeme:
                    if wf.lexeme.lemma and wf.lexeme.lemma[0].islower():
                        wf.add(
                            "Pamatforma",
                            wf.lexeme.lemma[:1].upper() + wf.lexeme.lemma[1:],
                        )

        # Pronoun lexicon entries lack Persona/Dzimte/Skaitlis for personal/
        # demonstrative pronouns (everything stamped Nepiemīt). Fill from a
        # token-level table — these are closed classes, ~50 forms total.
        if result.is_recognized():
            _fill_pronoun_attributes(result, word)
            _override_verb_transitivity(result)
            _override_verb_type(result)
            _override_adverb_pakape(result)

        if self.enable_prefixes and (
            not result.is_recognized()
            or (
                word.startswith(self._negation_prefix)
                and not _result_has_attr(result, "Vārdšķira", "Darbības vārds")
            )
            or _result_has_attr(result, "Izteiksme", "Divdabis")
        ):
            for wf in self._guess_by_prefix(word, original).wordforms:
                result.add_wordform(wf)

        # Hardcoded regex fallbacks for numbers, ordinals, abbreviations
        # (Java Analyzer.java lines 286-289 + analyzeAfter section).
        if not result.is_recognized():
            for wf in self._regex_fallback(word, original):
                result.add_wordform(wf)

        if not result.is_recognized() and self.enable_guessing:
            for wf in self.guess_by_ending(word, original).wordforms:
                result.add_wordform(wf)

        if result.is_recognized() and (self.remove_rare_words or self.remove_regional_words):
            self._filter_rare(result)
        return result

    # --- prefix-based guessing -----------------------------------------

    @property
    def _negation_prefix(self) -> str:
        prefixes = self.paradigms.prefixes_for("lv")
        return prefixes.negation[0] if prefixes and prefixes.negation else "ne"

    @property
    def _debitive_prefix(self) -> str:
        prefixes = self.paradigms.prefixes_for("lv")
        return prefixes.debitive[0] if prefixes and prefixes.debitive else "jā"

    @property
    def _superlative_prefix(self) -> str:
        prefixes = self.paradigms.prefixes_for("lv")
        return prefixes.superlative[0] if prefixes and prefixes.superlative else "vis"

    @property
    def _verb_prefixes(self) -> tuple[str, ...]:
        prefixes = self.paradigms.prefixes_for("lv")
        return prefixes.verb if prefixes else ()

    def _guess_by_prefix(self, word: str, original: str) -> Word:
        """Mirror of Java `guessByPrefix`. Strip a verb prefix, re-analyze the
        residue, and keep readings whose paradigm has a `Konjugācija` (verb-derived)."""
        result = Word(word)
        if " " in word:
            return result

        debitive = False
        cur = word
        if cur.startswith(self._debitive_prefix):
            debitive = True
            cur = cur[len(self._debitive_prefix):]

        for prefix in self._verb_prefixes:
            if cur.startswith(self._superlative_prefix + prefix):
                residue = self._superlative_prefix + cur[len(self._superlative_prefix) + len(prefix):]
                if debitive:
                    residue = self._debitive_prefix + residue
                self._add_prefix_readings(result, prefix, residue, with_superlative_prefix=True)
            elif cur.startswith(prefix):
                residue = cur[len(prefix):]
                if debitive:
                    residue = self._debitive_prefix + residue
                self._add_prefix_readings(result, prefix, residue, with_superlative_prefix=False)
        return result

    # --- diminutive + derived noun guessing ----------------------------

    def _guess_diminutive(
        self, word: str, result: Word, ending: Ending, sv, original: str
    ) -> None:
        """Mirror of Java `guessDeminutive` (lines 389-446).

        Two patterns: -īt- (paradigms supporting it) and -iņ- (with consonant
        alternation handling for noun-1b: galds → galdiņš)."""
        paradigm = ending.paradigm
        if paradigm is None:
            return
        derivations = paradigm.own_attributes.get("Paradigmai atļautie atvasinājumi") or ""
        # -īt- diminutive
        if sv.celms.endswith("īt") and "Deminutīvs -īt" in derivations:
            base = sv.celms[:-2]
            self._add_diminutive_readings(word, result, ending, sv, original, base, "-īt-", "īt")
        # -iņ- diminutive (most common Latvian diminutive)
        if sv.celms.endswith("iņ") and "Deminutīvs -iņ" in derivations:
            base = sv.celms[:-2]
            # Noun-1b: declension changes (galds:noun-1 → galdiņš:noun-2). Also
            # try inverse consonant alternations (dz→g, c→k).
            candidates = [base]
            if base.endswith("dz"):
                candidates.append(base[:-2] + "g")
            if base.endswith("c"):
                candidates.append(base[:-1] + "k")
            # Skip illegal soft-consonant diminutives (ceļiņš from ceļš etc.)
            if base.endswith(("ļ", "k", "g")) and paradigm.name == "noun-1b":
                return
            for cand in candidates:
                self._add_diminutive_readings(
                    word, result, ending, sv, original, cand, "-iņ-", "iņ"
                )

    def _add_diminutive_readings(
        self,
        word: str,
        result: Word,
        ending: Ending,
        sv,
        original: str,
        base_stem: str,
        marker: str,
        suffix: str,
    ) -> None:
        paradigm = ending.paradigm
        if paradigm is None:
            return
        lexemes = self._lexemes_with_stem(
            paradigm.id, paradigm.language, base_stem, ending.stem_type
        )
        for lexeme in lexemes:
            wf = Wordform(word, lexeme=lexeme, ending=ending, attributes=sv)
            wf.add("Pamazinājums", marker)
            wf.add("Avots", "pamazināmo formu atvasināšana")
            wf.add("Minējums", "Pamazinājums")
            le = paradigm.lemma_ending()
            if lexeme.lemma:
                wf.add("Avota pamatforma", lexeme.lemma)
            if le is not None:
                final_lemma = base_stem + suffix + le.ending
                wf.add("Pamatforma", _recap_for_lemma(final_lemma, original))
            result.add_wordform(wf)

    def _guess_derived_noun(
        self, word: str, result: Word, ending: Ending, sv, original: str
    ) -> None:
        """Mirror of Java `guessDerivedNoun` (lines 339-384). Recognizes
        -tājs/-tāja and -ējs/-ēja agentive nouns derived from verbs."""
        paradigm = ending.paradigm
        if paradigm is None:
            return
        derivations = paradigm.own_attributes.get("Paradigmai atļautie atvasinājumi") or ""
        if "tājs" not in derivations and "ējs" not in derivations:
            return

        # -tāj- agentive (lasītājs from lasīt)
        if sv.celms.endswith("tāj"):
            verb_stem = sv.celms[:-3]
            for verb_paradigm_name in ("verb-1", "verb-2", "verb-3a"):
                verb_paradigm = self.paradigms.by_name(verb_paradigm_name)
                if verb_paradigm is None:
                    continue
                lexemes = self._lexemes_with_stem(
                    verb_paradigm.id, "lv", verb_stem, StemType.BASE
                )
                for lexeme in lexemes:
                    wf = Wordform(word, lexeme=lexeme, ending=ending, attributes=sv)
                    wf.add("Avots", "-tājs/-tāja sufiksāls atvasinājums")
                    if lexeme.lemma:
                        wf.add("Avota pamatforma", lexeme.lemma)
                    wf.add("Minējums", "Pamazinājums")
                    le = paradigm.lemma_ending()
                    if le is not None:
                        # Build final lemma by attaching tāj + paradigm's lemma ending
                        final_lemma = lexeme.stems.get(StemType.BASE, verb_stem) + "tāj" + le.ending
                        wf.add("Pamatforma", _recap_for_lemma(final_lemma, original))
                    result.add_wordform(wf)

        # -ēj- agentive (e.g. cēlējs from celt)
        elif sv.celms.endswith("ēj"):
            verb_stem_raw = sv.celms[:-2]
            # 1st-conj -is participle mija (case 14) backwards
            from tezaurs.mijas import mija_variants as _mv

            verb_paradigm = self.paradigms.by_name("verb-1")
            if verb_paradigm is None:
                return
            for verb_variant in _mv(verb_stem_raw, 14, False):
                lexemes = self._lexemes_with_stem(
                    verb_paradigm.id, "lv", verb_variant.celms, StemType.PAST
                )
                for lexeme in lexemes:
                    wf = Wordform(word, lexeme=lexeme, ending=ending, attributes=sv)
                    wf.add_all(verb_variant)
                    wf.add("Avots", "-ējs/-ēja sufiksāls atvasinājums")
                    if lexeme.lemma:
                        wf.add("Avota pamatforma", lexeme.lemma)
                    wf.add("Minējums", "Pamazinājums")
                    le = paradigm.lemma_ending()
                    if le is not None:
                        final_lemma = verb_variant.celms + "ēj" + le.ending
                        wf.add("Pamatforma", _recap_for_lemma(final_lemma, original))
                    result.add_wordform(wf)

    # --- ending-based guessing (for unknown words) ---------------------

    def guess_by_ending(self, word: str, original: str) -> Word:
        """Heuristic for unknown words: try every paradigm whose ending suffix
        matches `word`, generate candidate lemmas via mija, return as
        unconfirmed `Wordform`s tagged with `Minējums = Galotne`.

        Mirror of Java `guessByEnding` (516-590). The Java loop tries longer
        endings first, breaks early if anything was found (unless
        `enableAllGuesses`)."""
        result = Word(word)
        proper_name = _is_first_capitalized(original)

        for length in range(len(word) - 2, -1, -1):
            for ending in self._all_endings.matched_endings(word):
                if len(ending.ending) != length:
                    continue
                paradigm = ending.paradigm
                if paradigm is None:
                    continue
                if paradigm.own_attributes.is_matching_strong(
                    "Paradigmas īpatnības", "Šablona vārdformas"
                ):
                    continue  # hardcoded paradigms can't be guessed

                stem_from_ending = ending.stem(word)
                stem_variants = mija_variants(stem_from_ending, ending.mija, proper_name)
                for sv in stem_variants:
                    stem = sv.celms
                    # Allowed-guess char check: stem must end with one of paradigm's allowed chars
                    if not _allowed_guess(paradigm, stem):
                        # Special exception for proper-noun feminine/masculine names
                        if proper_name and paradigm.name in ("noun-4m", "noun-4ma", "noun-3f"):
                            pass
                        else:
                            continue
                    wf = Wordform(word, lexeme=None, ending=ending, attributes=sv)
                    wf.add("Avots", "minējums pēc galotnes")
                    wf.add("Minējums", "Galotne")
                    le = paradigm.lemma_ending()
                    if le is not None:
                        wf.add("Pamatforma", _recap_for_lemma(stem + le.ending, original))
                    if self._is_guessable(wf, ending, paradigm, length):
                        result.add_wordform(wf)
            if result.is_recognized() and length > 0:
                # Break early unless we want every-length guesses; mostly the long
                # endings are already enough. The Java code bails for non-`-o` words.
                if not word.endswith("o"):
                    break
        return result

    def _is_guessable(
        self, wf: Wordform, ending: Ending, paradigm, length: int
    ) -> bool:
        """Filter from Java line 558-571: which guesses are emitted."""
        pos = paradigm.own_attributes.get("Vārdšķira")
        is_noun = pos == "Lietvārds"
        is_verb = pos == "Darbības vārds"
        is_adj = pos == "Īpašības vārds"
        is_residual = pos == "Reziduālis"
        is_participle = wf.is_matching_strong("Izteiksme", "Divdabis")

        ok = False
        if is_noun and (self.enable_vocative or not wf.is_matching_strong("Locījums", "Vokatīvs")):
            ok = True
        if is_verb:
            ok = True
        if is_adj:
            ok = True
        if is_participle:
            ok = True
        if is_residual:
            ok = True
        if not ok:
            return False
        # Endingless guesses (length=0) only allowed for special declensions
        if length == 0:
            return (
                wf.is_matching_strong("Deklinācija", "Nelokāms")
                or wf.is_matching_strong("Deklinācija", "Ģenitīveniskais")
                or is_residual
            )
        return True

    def _add_prefix_readings(
        self, result: Word, prefix: str, residue: str, *, with_superlative_prefix: bool
    ) -> None:
        prefixless = self._analyze_lowercase(residue, residue)
        for wf in prefixless.wordforms:
            paradigm = wf.ending.paradigm if wf.ending else None
            if paradigm is None or paradigm.own_attributes.get("Konjugācija") is None:
                continue  # only verb-derived classes get prefix expansion
            # Skip ne- + debitive forms
            if prefix == self._negation_prefix and (
                wf.is_matching_strong("Izteiksme", "Vajadzības")
                or wf.is_matching_strong("Izteiksme", "Vajadzības, atstāstījuma paveids")
                or wf.is_matching_strong("Noliegums", "Jā")
            ):
                continue
            # Skip awkward "vis-" + verb-prefix combos
            if (
                wf.is_matching_strong("Pakāpe", "Vispārākā")
                and not with_superlative_prefix
            ):
                continue
            wf.add("Avots", "priedēkļu atvasināšana")
            wf.add("Priedēklis", prefix)
            if (
                prefix != self._negation_prefix
                or not wf.is_matching_weak("Vārdšķira", "Darbības vārds")
            ):
                # Update lemma to include the prefix
                if wf.lexeme and wf.lexeme.lemma:
                    wf.add("Pamatforma", prefix + wf.lexeme.lemma)
            wf.add("Minējums", "Priedēklis")
            wf.add("Noliegums", "Jā" if prefix == self._negation_prefix else "Nē")
            result.add_wordform(wf)

    def analyze_lemma(self, word: str) -> Word:
        """Analyze, but keep only readings whose ending IS the lemma ending of its paradigm."""
        full = self.analyze(word)
        kept = Word(full.token)
        for wf in full.wordforms:
            if wf.ending and wf.ending.paradigm and wf.ending.id == wf.ending.paradigm.lemma_ending_id:
                kept.add_wordform(wf)
        return kept

    # --- per-paradigm stem index (lazy) --------------------------------

    def _hardcoded_lexemes(self, surface_form: str) -> list[Lexeme]:
        """Return Lexemes from the `hardcoded` paradigm whose stem1 (= the
        actual surface form for these entries) matches `surface_form`."""
        if self._hardcoded_form_index is None:
            self._build_hardcoded_index()
        return self._hardcoded_form_index.get(surface_form, [])

    def _build_hardcoded_index(self) -> None:
        """One-time scan of `hardcoded` paradigm rows. ~5K entries; <100ms."""
        import json as _json
        import pyarrow.compute as pc

        idx: dict[str, list[Lexeme]] = defaultdict(list)
        t = self.lexicon.table
        mask = pc.or_kleene(
            pc.equal(t["paradigm_id"], 29),
            pc.equal(t["paradigm_name"], "hardcoded"),
        )
        sub = t.filter(mask)
        # Resolve paradigm per-row — `hardcoded` exists in both LV (id=29) and
        # LTG (id=100). `by_name` doesn't disambiguate, so we lookup by (id, lang).
        for row in sub.to_pylist():
            stem = row.get("stem1")
            lemma = row.get("lemma")
            if stem is None:
                continue
            language = row["language"]
            paradigm_id = row.get("paradigm_id") or 29
            paradigm = self.paradigms.by_id(paradigm_id, language)
            if paradigm is None:
                # Fall back to language-matching by_name lookup
                for p in self.paradigms.paradigms:
                    if p.name == "hardcoded" and p.language == language:
                        paradigm = p
                        break
            attrs_json = row.get("attributes_json")
            attrs = AttributeValues(_json.loads(attrs_json) if attrs_json else {})
            lexeme = Lexeme(
                lexeme_id=row.get("lexeme_id"),
                entry_id=row.get("entry_id"),
                human_id=row.get("human_id"),
                lemma=lemma,
                stems={StemType.BASE: stem},
                paradigm=paradigm,
                own_attributes=attrs,
                source=row["source"],
                language=language,
            )
            idx[stem].append(lexeme)
        self._hardcoded_form_index = dict(idx)

    def _lexemes_with_stem(
        self, paradigm_id: int, language: str, stem: str, stem_type: StemType
    ) -> list[Lexeme]:
        """Return lexemes in the given paradigm whose stem at `stem_type` matches.

        Stores only stem→[row_index] mappings; Lexeme objects are materialised
        lazily on lookup with an LRU cache. This keeps memory at ~10 MB for
        the index instead of ~870 MB if every Lexeme were eagerly built.
        """
        key = (paradigm_id, language, stem_type)
        idx = self._stem_index.get(key)
        if idx is None:
            idx = self._build_stem_index(paradigm_id, language, stem_type)
            self._stem_index[key] = idx
        rows = idx.get(stem)
        if not rows:
            return []
        return [self._materialize_lexeme(r, paradigm_id, language) for r in rows]

    def _materialize_lexeme(
        self, row_idx: int, paradigm_id: int, language: str
    ) -> Lexeme:
        """Materialise a Lexeme from its parquet row index. LRU-cached so hot
        lookups stay fast without paying the eager-build memory cost."""
        cache_key = (row_idx, paradigm_id, language)
        cached = self._lexeme_cache.get(cache_key)
        if cached is not None:
            return cached
        t = self.lexicon.table
        row = {col: t[col][row_idx].as_py() for col in t.schema.names}
        paradigm = self.paradigms.by_id(paradigm_id, language)

        import json as _json
        attributes_json = row.get("attributes_json")
        attrs = AttributeValues(_json.loads(attributes_json) if attributes_json else {})

        stem1 = row.get("stem1")
        # JSONL rows lack any stem — derive from lemma.
        if stem1 is None and row.get("lemma") and paradigm is not None:
            le = paradigm.lemma_ending()
            lemma = row["lemma"]
            if le is not None and lemma.endswith(le.ending):
                stem1 = lemma[: len(lemma) - len(le.ending)] if le.ending else lemma
        stems = {StemType.BASE: stem1 or row.get("lemma") or ""}
        if row.get("stem2"):
            stems[StemType.PRESENT] = row["stem2"]
        if row.get("stem3"):
            stems[StemType.PAST] = row["stem3"]
        lexeme = Lexeme(
            lexeme_id=row.get("lexeme_id"),
            entry_id=row.get("entry_id"),
            human_id=row.get("human_id"),
            lemma=row.get("lemma"),
            stems=stems,
            paradigm=paradigm,
            own_attributes=attrs,
            source=row["source"],
            language=row["language"],
        )
        # Bounded cache (LRU-ish via dict insertion order).
        self._lexeme_cache[cache_key] = lexeme
        if len(self._lexeme_cache) > self._LEXEME_CACHE_SIZE:
            # Evict oldest 10% to keep dict from growing unbounded.
            for k in list(self._lexeme_cache.keys())[: self._LEXEME_CACHE_SIZE // 10]:
                self._lexeme_cache.pop(k, None)
        return lexeme

    def _build_stem_index(
        self, paradigm_id: int, language: str, stem_type: StemType
    ) -> dict[str, list[int]]:
        """Build (stem → [row_idx]) for one (paradigm, language, stem_type).

        Batch-extracts the three columns needed (stem1, target stem, lemma) in
        a single `to_pylist()` per column to avoid the per-row pyarrow scalar
        overhead. Stores integer row offsets; Lexemes materialise in
        `_materialize_lexeme`.
        """
        t = self.lexicon.table
        import pyarrow.compute as pc

        paradigm = self.paradigms.by_id(paradigm_id, language)
        id_match = pc.equal(t["paradigm_id"], paradigm_id)
        name_match = (
            pc.equal(t["paradigm_name"], paradigm.name)
            if paradigm is not None and paradigm.name
            else pc.equal(t["paradigm_name"], "__never_matches__")
        )
        either = pc.or_kleene(id_match, name_match)
        mask = pc.and_kleene(either, pc.equal(t["language"], language))
        # Keep indices as a pyarrow array for `take()`; convert to Python list
        # only after extraction.
        indices_arr = pc.indices_nonzero(mask)
        indices = indices_arr.to_pylist()
        if not indices:
            return defaultdict(list)

        stem_col_name = {
            StemType.BASE: "stem1",
            StemType.PRESENT: "stem2",
            StemType.PAST: "stem3",
        }[stem_type]

        # Project just the columns we need and take only the matching rows.
        # Use a deduped column list so we don't pass duplicates when
        # stem_col_name == "stem1".
        cols = list(dict.fromkeys(["stem1", stem_col_name, "lemma"]))
        sub = t.select(cols).take(indices_arr)
        stem1_list = sub["stem1"].to_pylist()
        target_list = sub[stem_col_name].to_pylist() if stem_col_name != "stem1" else stem1_list
        lemma_list = sub["lemma"].to_pylist()

        le = paradigm.lemma_ending() if paradigm is not None else None
        le_str = le.ending if le is not None else None
        idx: dict[str, list[int]] = defaultdict(list)
        for offset, row_idx in enumerate(indices):
            stem = target_list[offset] or stem1_list[offset]
            if stem is None:
                lemma = lemma_list[offset]
                if lemma and le_str is not None and lemma.endswith(le_str):
                    stem = lemma[: len(lemma) - len(le_str)] if le_str else lemma
            if stem is None:
                continue
            idx[stem].append(row_idx)
        return idx

    # --- filters --------------------------------------------------------

    def _is_acceptable(self, wf: Wordform) -> bool:
        """Drop singularia-tantum used as plural, vocatives when disabled, etc."""
        if not self.enable_vocative and wf.is_matching_strong("Locījums", "Vokatīvs"):
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

    # --- regex fallbacks (numbers, ordinals, abbreviations, residuals) ----

    _RE_ORDINAL = re.compile(r"^\d+\.$")
    _RE_NUMBER = re.compile(r"^[\d., ]*[\d⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]+([.,][-‐‑‒–—―])?$")
    _RE_FRACTION = re.compile(r"^\d+[\\/]\d+$")
    _RE_ABBREV = re.compile(r"^\w+\.$")
    _RE_LETTER = re.compile(r"^[\W\d_]*[\w][\W\d_]*$")  # single letter token

    def _regex_fallback(self, word: str, original: str) -> list[Wordform]:
        """Hardcoded patterns for numbers, ordinals, abbreviations, isolated letters."""
        results: list[Wordform] = []
        # Ordinal: e.g. "2006." — gold tag 'xo' (Kārtas skaitlis cipariem)
        if self._RE_ORDINAL.match(word):
            wf = Wordform(word)
            wf.add("Vārdšķira", "Reziduālis")
            wf.add("Reziduāļa tips", "Kārtas skaitlis cipariem")
            wf.add("Pamatforma", word)
            wf.add("Minējums", "Galotne")
            results.append(wf)
            return results
        # Plain number: "2", "1996", "1,5", "10 000" — gold tag 'xn' (Skaitlis cipariem)
        if self._RE_NUMBER.match(word) or self._RE_FRACTION.match(word):
            wf = Wordform(word)
            wf.add("Vārdšķira", "Reziduālis")
            wf.add("Reziduāļa tips", "Skaitlis cipariem")
            wf.add("Pamatforma", word)
            wf.add("Minējums", "Galotne")
            results.append(wf)
            return results
        # Single-letter token (often initials): "K.", "X"
        if len(word) <= 3 and word.endswith(".") and word[:-1].isalpha():
            wf = Wordform(word)
            wf.add("Vārdšķira", "Saīsinājums")
            wf.add("Pamatforma", word.lower())
            wf.add("Minējums", "Galotne")
            results.append(wf)
            return results
        if self._RE_ABBREV.match(word):
            wf = Wordform(word)
            wf.add("Vārdšķira", "Saīsinājums")
            wf.add("Pamatforma", word.lower())
            wf.add("Minējums", "Galotne")
            # Single capital letter + period (L. S. A. K.) almost always
            # marks an initial — default to proper-noun abbreviation.
            stem = word.rstrip(".")
            if len(stem) <= 2 and stem and stem[0].isupper():
                wf.add("Saīsinājuma tips", "Īpašvārds")
                wf.add("Pamatforma", word)
            results.append(wf)
            return results
        return results

    def _filter_rare(self, word: Word) -> None:
        """Drop rare/regional/outdated readings if non-rare alternatives exist."""

        def is_rare(wf: Wordform) -> bool:
            return wf.is_matching_strong("Biežums", "Reti") or wf.is_matching_strong(
                "Lietojums", "Novecojis"
            )

        def is_regional(wf: Wordform) -> bool:
            return wf.is_matching_strong("Lietojums", "Apvidvārds") or wf.is_matching_strong(
                "Lietojums", "Apvidvārds, novecojis"
            )

        has_nonrare = any(not is_rare(wf) for wf in word.wordforms)
        kept: list[Wordform] = []
        for wf in word.wordforms:
            if self.remove_rare_words and has_nonrare and is_rare(wf):
                continue
            if self.remove_regional_words and is_regional(wf):
                continue
            kept.append(wf)
        word.wordforms = kept


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _allowed_guess(paradigm, stem: str) -> bool:
    """True if the paradigm allows a stem ending in `stem`'s last char.

    `paradigm.allowed_guess_endings` is a string of permitted last-char chars.
    None or empty means anything goes.
    """
    chars = paradigm.allowed_guess_endings
    if not chars:
        return True
    if not stem:
        return False
    return stem[-1] in chars


def _recap_for_lemma(form: str, original: str) -> str:
    """Match capitalization of `form` to `original`."""
    if not form or not original:
        return form
    if original[0].isupper():
        return form[:1].upper() + form[1:]
    return form


def _promote_matching(word: Word, target_tag: str, target_lemma: str) -> None:
    """Move the first wordform whose (tag, lemma) matches the targets to the front."""
    from tezaurs.markup import to_tag

    for i, wf in enumerate(word.wordforms):
        if i == 0:
            continue
        l = wf.lexeme.lemma if wf.lexeme else (wf.get("Pamatforma") or "")
        if to_tag(wf) == target_tag and l.casefold() == target_lemma.casefold():
            word.wordforms = [wf] + [w for w in word.wordforms if w is not wf]
            return


def _apply_form_override(
    word: Word, surface: str, target_tag: str, target_lemma: str
) -> None:
    """High-confidence form override.

    First try to promote an existing wordform matching (tag, lemma). If none
    exists, synthesise a Wordform with attributes parsed from the target tag
    and insert at the front. This is the only pathway that beats the
    candidate-set ceiling — by design it relies on the corpus annotation
    being authoritative for these high-confidence forms.
    """
    from tezaurs.markup import to_tag, from_tag

    # Try promote first.
    for i, wf in enumerate(word.wordforms):
        if i == 0:
            continue
        l = wf.lexeme.lemma if wf.lexeme else (wf.get("Pamatforma") or "")
        if to_tag(wf) == target_tag and l.casefold() == target_lemma.casefold():
            word.wordforms = [wf] + [w for w in word.wordforms if w is not wf]
            return

    # Top reading already matches?
    if word.wordforms:
        top = word.wordforms[0]
        l = top.lexeme.lemma if top.lexeme else (top.get("Pamatforma") or "")
        if to_tag(top) == target_tag and l.casefold() == target_lemma.casefold():
            return

    # Synthesise: attributes from from_tag(target_tag), keep top's lexeme as
    # a stand-in, override Pamatforma to the corpus-confident lemma. This
    # affects to_tag() emission and the parity-test lemma read path.
    base = word.wordforms[0] if word.wordforms else None
    synth = Wordform(
        surface,
        lexeme=base.lexeme if base else None,
        ending=base.ending if base else None,
    )
    parsed = from_tag(target_tag)
    for k, v in parsed:
        synth.add(k, v)
    synth.add("Pamatforma", target_lemma)
    synth.add("Minējums", "Korpusa override")
    word.wordforms.insert(0, synth)


def _result_has_attr(word: Word, attribute: str, value: str) -> bool:
    return any(wf.is_matching_strong(attribute, value) for wf in word.wordforms)


def _is_first_capitalized(word: str) -> bool:
    return bool(word) and word[0].isupper() and word[1:].islower()


def _detect_case(word: str) -> str:
    """Match Java's `i_CapitalLetters`: `Pirmais lielais` / `Visi lielie` / `Mazie`."""
    if word.isupper():
        return "Visi lielie"
    if _is_first_capitalized(word):
        return "Pirmais lielais"
    return "Mazie"


# Pronoun forms whose lexicon entries are missing Persona/Dzimte/Skaitlis.
# Keyed by (lowercase form, lemma). Value: dict of overrides to apply when
# the existing attribute is "Nepiemīt". Personal pronouns (es/tu/...) and
# 3rd-person demonstratives (tas/tā/šis/šī) — closed class, ~60 entries.
_PRONOUN_ATTRS: dict[tuple[str, str], dict[str, str]] = {
    # 1st person personal
    ("es", "es"): {"Persona": "1", "Skaitlis": "Vienskaitlis"},
    ("manis", "es"): {"Persona": "1", "Skaitlis": "Vienskaitlis"},
    ("man", "es"): {"Persona": "1", "Skaitlis": "Vienskaitlis"},
    ("mani", "es"): {"Persona": "1", "Skaitlis": "Vienskaitlis"},
    ("manī", "es"): {"Persona": "1", "Skaitlis": "Vienskaitlis"},
    ("mēs", "mēs"): {"Persona": "1", "Skaitlis": "Daudzskaitlis"},
    ("mūsu", "mēs"): {"Persona": "1", "Skaitlis": "Daudzskaitlis"},
    ("mums", "mēs"): {"Persona": "1", "Skaitlis": "Daudzskaitlis"},
    ("mūs", "mēs"): {"Persona": "1", "Skaitlis": "Daudzskaitlis"},
    ("mūsos", "mēs"): {"Persona": "1", "Skaitlis": "Daudzskaitlis"},
    # 2nd person personal
    ("tu", "tu"): {"Persona": "2", "Skaitlis": "Vienskaitlis"},
    ("tevis", "tu"): {"Persona": "2", "Skaitlis": "Vienskaitlis"},
    ("tev", "tu"): {"Persona": "2", "Skaitlis": "Vienskaitlis"},
    ("tevi", "tu"): {"Persona": "2", "Skaitlis": "Vienskaitlis"},
    ("tevī", "tu"): {"Persona": "2", "Skaitlis": "Vienskaitlis"},
    ("jūs", "jūs"): {"Persona": "2", "Skaitlis": "Daudzskaitlis"},
    ("jūsu", "jūs"): {"Persona": "2", "Skaitlis": "Daudzskaitlis"},
    ("jums", "jūs"): {"Persona": "2", "Skaitlis": "Daudzskaitlis"},
    ("jūsos", "jūs"): {"Persona": "2", "Skaitlis": "Daudzskaitlis"},
    # 3rd person personal — viņš (m sg)
    ("viņš", "viņš"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("viņa", "viņš"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("viņam", "viņš"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("viņu", "viņš"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("viņā", "viņš"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("viņi", "viņš"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("viņus", "viņš"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("viņiem", "viņš"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("viņos", "viņš"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    # 3rd person personal — viņa (f sg) / viņas (f pl)
    ("viņas", "viņa"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    ("viņai", "viņa"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("viņām", "viņa"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    # Reflexive
    ("sevis", "sevis"): {"Persona": "0"},
    ("sev", "sevis"): {"Persona": "0"},
    ("sevi", "sevis"): {"Persona": "0"},
    ("sevī", "sevis"): {"Persona": "0"},
    # Demonstrative — tas (m) / tā (f)
    ("tas", "tas"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("tā", "tas"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("tā", "tā"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("tām", "tā"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    ("tām", "tas"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    ("tam", "tas"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("to", "tas"): {"Persona": "3"},
    ("to", "tā"): {"Persona": "3", "Dzimte": "Sieviešu"},
    ("tai", "tā"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("tai", "tas"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("tās", "tā"): {"Persona": "3", "Dzimte": "Sieviešu"},
    ("tās", "tas"): {"Persona": "3", "Dzimte": "Sieviešu"},
    ("tie", "tas"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("tos", "tas"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("tiem", "tas"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("tajā", "tas"): {"Persona": "3", "Skaitlis": "Vienskaitlis"},
    ("tajos", "tas"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("tajās", "tā"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    # Demonstrative — šis (m) / šī (f)
    ("šis", "šis"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("šī", "šī"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("šī", "šis"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("šim", "šis"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("šo", "šis"): {"Persona": "3"},
    ("šo", "šī"): {"Persona": "3", "Dzimte": "Sieviešu"},
    ("šai", "šī"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("šās", "šī"): {"Persona": "3", "Dzimte": "Sieviešu"},
    ("šīs", "šī"): {"Persona": "3", "Dzimte": "Sieviešu"},
    ("šie", "šis"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("šos", "šis"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("šiem", "šis"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("šajā", "šis"): {"Persona": "3", "Skaitlis": "Vienskaitlis"},
    ("šajos", "šis"): {"Persona": "3", "Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("šajās", "šī"): {"Persona": "3", "Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
}


def _add_proper_noun_reading(result: Word, original: str) -> None:
    """For mid-sentence capitalized tokens whose readings are all common
    nouns (Sugas vārds), insert a proper-noun (Īpašvārds) variant at the top
    of the candidate list. The CRF/classifier then disambiguates which one
    fits the sentence context.
    """
    if not result.wordforms:
        return
    has_proper = any(
        wf.is_matching_strong("Lietvārda tips", "Īpašvārds")
        for wf in result.wordforms
    )
    if has_proper:
        return
    # Only operate on noun readings — verbs/pronouns/etc capitalized
    # mid-sentence are too rare to invent.
    noun_readings = [
        wf for wf in result.wordforms
        if wf.get("Vārdšķira") == "Lietvārds"
    ]
    if not noun_readings:
        return
    # Take the first noun reading, copy its attributes, override to proper noun.
    base = noun_readings[0]
    proper = Wordform(base.token, lexeme=base.lexeme, ending=base.ending)
    for k, v in base:
        proper.add(k, v)
    proper.add("Lietvārda tips", "Īpašvārds")
    capitalized_lemma = (
        original[:1].upper() + base.lexeme.lemma[1:]
        if base.lexeme and base.lexeme.lemma
        else original
    )
    proper.add("Pamatforma", capitalized_lemma)
    proper.add("Minējums", "Īpašvārds")
    # Insert at front — CRF/classifier will rescore.
    result.wordforms.insert(0, proper)


def _override_verb_transitivity(result: Word) -> None:
    """Override Transitivitāte for verbs whose lemma is in the transitivity
    table built from gold-corpus statistics. Lexicon marks many common verbs
    as intransitive when ≥80% of corpus usage is transitive (and vice versa).
    """
    if not _VERB_TRANSITIVITY:
        return
    for wf in result.wordforms:
        if wf.get("Vārdšķira") != "Darbības vārds":
            continue
        lemma = wf.get("Pamatforma") or (wf.lexeme.lemma if wf.lexeme else None)
        if lemma is None:
            continue
        override = _VERB_TRANSITIVITY.get(lemma)
        if override is None:
            continue
        wf.add("Transitivitāte", _TRANS_LV[override])


def _override_verb_type(result: Word) -> None:
    """Override 'Darbības vārda tips' for modal/auxiliary verbs whose lexicon
    entry disagrees with gold-corpus tagging (varēt → Modāls modificētājs)."""
    if not _VERB_TYPE:
        return
    for wf in result.wordforms:
        if wf.get("Vārdšķira") != "Darbības vārds":
            continue
        lemma = wf.get("Pamatforma") or (wf.lexeme.lemma if wf.lexeme else None)
        if lemma is None:
            continue
        override = _VERB_TYPE.get(lemma)
        if override is None:
            continue
        wf.add("Darbības vārda tips", override)


def _override_adverb_pakape(result: Word) -> None:
    """Override Pakāpe for adverbs whose lemma consistently gets a different
    value in gold-corpus annotation than what the lexicon supplies."""
    if not _ADVERB_PAKAPE:
        return
    for wf in result.wordforms:
        if wf.get("Vārdšķira") != "Apstākļa vārds":
            continue
        lemma = wf.get("Pamatforma") or (wf.lexeme.lemma if wf.lexeme else None)
        if lemma is None:
            continue
        override = _ADVERB_PAKAPE.get(lemma)
        if override is None:
            continue
        wf.add("Pakāpe", override)


def _fill_pronoun_attributes(result: Word, form: str) -> None:
    """Override pronoun Persona/Dzimte/Skaitlis from a hardcoded form table,
    falling back to ending-based inference for adjective-like pronouns
    (savs/tavs/viss/cits/kāds/...) whose lexicon entries lack gender/number.

    Only updates attributes whose current value is "Nepiemīt" — preserves
    explicit data when present.
    """
    key_form = form.lower()
    for wf in result.wordforms:
        if wf.get("Vārdšķira") != "Vietniekvārds":
            continue
        lemma = wf.lexeme.lemma if wf.lexeme else None
        if lemma is None:
            continue
        # Negative pronouns (nekas/neviens/nekāds/...) carry inherent negation
        # that the lexicon doesn't stamp — set it from the lemma.
        if lemma.startswith("ne") and len(lemma) > 2:
            if wf.get("Noliegums") in (None, "Nē"):
                wf.add("Noliegums", "Jā")
        overrides = _PRONOUN_ATTRS.get((key_form, lemma))
        if overrides is None:
            # Adjective-like pronouns: derive Dzimte/Skaitlis from form ending
            # + already-known Locījums.
            overrides = _infer_adj_pronoun_attrs(key_form, wf.get("Locījums"))
        if overrides is None:
            continue
        for attr, value in overrides.items():
            current = wf.get(attr)
            if current is None or current == "Nepiemīt":
                wf.add(attr, value)


# (locījums, form_ending) → (Dzimte, Skaitlis) for adjective-like pronouns
# (savs/tavs/viss/cits/kāds/katrs/nekas/neviens/...). Mirrors the standard
# adjective declension. None means "ambiguous, leave alone".
_ADJ_PRONOUN_ENDINGS: dict[tuple[str, str], dict[str, str]] = {
    ("Nominatīvs", "s"): {"Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("Nominatīvs", "š"): {"Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("Nominatīvs", "a"): {"Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("Nominatīvs", "e"): {"Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("Nominatīvs", "i"): {"Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("Nominatīvs", "as"): {"Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    ("Nominatīvs", "es"): {"Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    ("Ģenitīvs", "a"): {"Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("Ģenitīvs", "as"): {"Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("Ģenitīvs", "es"): {"Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("Datīvs", "am"): {"Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("Datīvs", "ai"): {"Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("Datīvs", "iem"): {"Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("Datīvs", "ām"): {"Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    ("Datīvs", "ēm"): {"Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    ("Akuzatīvs", "u"): {"Skaitlis": "Vienskaitlis"},
    ("Akuzatīvs", "us"): {"Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("Akuzatīvs", "as"): {"Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    ("Akuzatīvs", "es"): {"Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    ("Lokatīvs", "ā"): {"Dzimte": "Vīriešu", "Skaitlis": "Vienskaitlis"},
    ("Lokatīvs", "ē"): {"Dzimte": "Sieviešu", "Skaitlis": "Vienskaitlis"},
    ("Lokatīvs", "os"): {"Dzimte": "Vīriešu", "Skaitlis": "Daudzskaitlis"},
    ("Lokatīvs", "ās"): {"Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
    ("Lokatīvs", "ēs"): {"Dzimte": "Sieviešu", "Skaitlis": "Daudzskaitlis"},
}


def _infer_adj_pronoun_attrs(form: str, locijums: str | None) -> dict[str, str] | None:
    """Try to derive Dzimte/Skaitlis from form ending + already-set Locījums."""
    if not locijums:
        return None
    for ending_len in (3, 2, 1):
        if len(form) > ending_len:
            ending = form[-ending_len:]
            attrs = _ADJ_PRONOUN_ENDINGS.get((locijums, ending))
            if attrs is not None:
                return attrs
    return None
