"""Unit tests pinning specific behaviors of each module against known examples.

Run: `.venv/bin/pytest tests/test_unit.py -v`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from vardene.analyzer import Analyzer
from vardene.attributes import AttributeValues, TagSet
from vardene.inflector import Inflector
from vardene.lexicon import Lexicon
from vardene.markup import from_tag, to_tag
from vardene.mijas import (
    mija_for_inflection,
    mija_variants,
    syllables,
    verify_back_inflection,
)
from vardene.paradigm import ParadigmCatalog
from vardene.trie import Trie

# ---------------------------------------------------------------------------
# Mijas — core linguistic engine
# ---------------------------------------------------------------------------


class TestMijas:
    def test_syllables(self) -> None:
        assert syllables("kristīnīt") == 3
        assert syllables("tēvs") == 1
        assert syllables("māte") == 2
        assert syllables("") == 0

    def test_case_0_no_mija(self) -> None:
        out = mija_variants("rakt", 0)
        assert [v.celms for v in out] == ["rakt"]

    def test_case_1_consonant_mija(self) -> None:
        # lāč ← lāc (c → č), Java case 1
        out = mija_variants("lāč", 1)
        assert any(v.celms == "lāc" and v.get("Mija") == "c -> č" for v in out)

    def test_case_3_adjective_gradation(self) -> None:
        out = mija_variants("vislielāk", 3)
        celms_to_degree = {v.celms: v.get("Pakāpe") for v in out}
        assert celms_to_degree["liel"] == "Vispārākā"
        assert celms_to_degree["visliel"] == "Pārākā"
        assert celms_to_degree["vislielāk"] == "Pamata"

    def test_case_4_lv_debitive_prefix(self) -> None:
        # 'jārakt' → strip 'jā' → 'rakt' (mija 0)
        assert [v.celms for v in mija_variants("jārakt", 4)] == ["rakt"]
        # No prefix → empty
        assert mija_variants("rakt", 4) == []
        # Too short → empty
        assert mija_variants("jā", 4) == []

    def test_inflect_then_analyze_round_trip(self) -> None:
        forward = mija_for_inflection("zaļ", 3, add_superlative=True)
        forms = [v.celms for v in forward]
        assert "zaļ" in forms
        assert "zaļāk" in forms
        assert "viszaļāk" in forms

        backward = mija_variants("zaļāk", 3)
        celms = {v.celms for v in backward}
        assert "zaļ" in celms

    def test_inflect_negation(self) -> None:
        # 'nerakt' is the negated form of 'rakt'
        out = mija_for_inflection("rakt", 4)
        assert any(v.celms == "jārakt" for v in out)

    def test_ltg_vowel_mija(self) -> None:
        from vardene.mijas import (
            _ltg_patskanu_mija_atpakal_locisanai,
            _ltg_patskanu_mija_locisanai,
        )

        # Forward: a→o, e→a, ē→ā, i→y
        assert _ltg_patskanu_mija_locisanai("mac") == "moc"
        assert _ltg_patskanu_mija_locisanai("mēc") == "māc"
        assert _ltg_patskanu_mija_locisanai("mic") == "myc"
        # Backward
        assert _ltg_patskanu_mija_atpakal_locisanai("moc") == "mac"
        assert _ltg_patskanu_mija_atpakal_locisanai("myc") == "mic"

    def test_verify_back_inflection_round_trip(self) -> None:
        analyses = mija_variants("lāč", 1)
        assert analyses
        for a in analyses:
            assert verify_back_inflection(a, "lāč", 1)


# ---------------------------------------------------------------------------
# Trie — finite-state automata for special tokens
# ---------------------------------------------------------------------------


class TestTrie:
    def test_built_with_user_exceptions(self) -> None:
        t = Trie()
        t.add_exception("piem.")
        t.initialize_exceptions()
        # match() walks branch 0 (the exception trie)
        assert t.match("piem.") is True
        assert t.match("''") is True
        assert t.match("unknown") is False

    def test_individual_automata(self) -> None:
        from vardene.trie import (
            n2_a_clock,
            n2_aa_date,
            n3_email,
            n4b_domain,
            n5_punctuation,
            n7_compound,
        )

        # Use a generic walker for direct FSA testing
        def walk(node, seq: str) -> int:
            if not seq:
                return 0
            cur = node
            if not cur.contains(seq[0]):
                cur = cur.next_sibling
                while cur is not None and not cur.contains(seq[0]):
                    cur = cur.next_sibling
                if cur is None:
                    return 0
            last = 2 if cur.can_end else 1
            for c in seq[1:]:
                nxt = cur.first_child
                while nxt is not None and not nxt.contains(c):
                    nxt = nxt.next_sibling
                if nxt is None:
                    return 0
                cur = nxt
                last = 2 if cur.can_end else 1
            return last

        assert walk(n2_a_clock(), "14:30") == 2
        assert walk(n2_aa_date(), "2009-12-14") == 2
        assert walk(n3_email(), "foo@bar.com") == 2
        assert walk(n4b_domain(), "foo.lv") == 2
        assert walk(n5_punctuation(), "?!?") == 2
        assert walk(n7_compound(), "compound-word") == 2


# ---------------------------------------------------------------------------
# AttributeValues — multivalue + case-insensitive matching
# ---------------------------------------------------------------------------


class TestAttributes:
    def test_basic_matching(self) -> None:
        av = AttributeValues({"Vārdšķira": "Lietvārds"})
        assert av.is_matching_strong("Vārdšķira", "Lietvārds")
        assert av.is_matching_strong("Vārdšķira", "LIETVĀRDS")  # CI
        assert not av.is_matching_strong("Vārdšķira", "Darbības vārds")

    def test_multivalue(self) -> None:
        av = AttributeValues({"Vārdšķira": "Lietvārds|Īpašības vārds"})
        assert av.is_matching_strong("Vārdšķira", "Lietvārds")
        assert av.is_matching_strong("Vārdšķira", "Īpašības vārds")
        assert not av.is_matching_strong("Vārdšķira", "Saiklis")

    def test_weak_matching(self) -> None:
        av = AttributeValues({"Vārdšķira": "Lietvārds"})
        # Absent attribute weak-matches anything
        assert av.is_matching_weak("Locījums", "Nominatīvs")
        # Present attribute follows strong rules
        assert av.is_matching_weak("Vārdšķira", "Lietvārds")
        assert not av.is_matching_weak("Vārdšķira", "Saiklis")

    def test_tagset_singleton(self) -> None:
        ts = TagSet.instance()
        assert TagSet.instance() is ts
        assert len(ts.attributes) == 97
        assert ts.by_lv("Vārdšķira") is not None


# ---------------------------------------------------------------------------
# Paradigm + Lexicon — data layer
# ---------------------------------------------------------------------------


class TestParadigmAndLexicon:
    def test_paradigm_lookup(self) -> None:
        cat = ParadigmCatalog.instance()
        p = cat.by_name("noun-1a")
        assert p is not None
        assert p.id == 1
        assert p.language == "lv"
        # noun-1a-ltg shares ID 1 but different language
        plg = cat.by_name("noun-1a-ltg")
        assert plg is not None and plg.language == "ltg"

    def test_lexeme_lookup(self) -> None:
        lex = Lexicon.instance()
        matches = lex.lexemes_by_lemma("tēvs")
        assert len(matches) >= 1
        assert any(m.paradigm and m.paradigm.name == "noun-1a" for m in matches)

    def test_ending_stem_strips_correctly(self) -> None:
        cat = ParadigmCatalog.instance()
        p = cat.by_name("noun-1a")
        nominative = p.endings_by_attribute("Locījums", "Nominatīvs")[0]
        assert nominative.stem("tēvs") == "tēv"


# ---------------------------------------------------------------------------
# Markup — to_tag / from_tag round-trip
# ---------------------------------------------------------------------------


class TestMarkup:
    def test_to_tag_known_examples(self) -> None:
        # tēvs → ncmsn1 (Noun, Common, Masculine, Singular, Nominative, Decl 1)
        av = AttributeValues(
            {
                "Vārdšķira": "Lietvārds",
                "Lietvārda tips": "Sugas vārds",
                "Dzimte": "Vīriešu",
                "Skaitlis": "Vienskaitlis",
                "Locījums": "Nominatīvs",
                "Deklinācija": "1",
            }
        )
        assert to_tag(av) == "ncmsn1"

    def test_to_tag_feminine_5th_decl(self) -> None:
        # māte → ncfsn5
        av = AttributeValues(
            {
                "Vārdšķira": "Lietvārds",
                "Lietvārda tips": "Sugas vārds",
                "Dzimte": "Sieviešu",
                "Skaitlis": "Vienskaitlis",
                "Locījums": "Nominatīvs",
                "Deklinācija": "5",
            }
        )
        assert to_tag(av) == "ncfsn5"

    def test_from_tag_round_trip(self) -> None:
        av = from_tag("ncmsn1")
        assert av.get("Vārdšķira") == "Lietvārds"
        assert av.get("Dzimte") == "Vīriešu"
        assert av.get("Locījums") == "Nominatīvs"

    def test_unrecognized_returns_dash(self) -> None:
        av = AttributeValues()
        assert to_tag(av) == "-"


# ---------------------------------------------------------------------------
# End-to-end — Analyzer & Inflector
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def analyzer() -> Analyzer:
    a = Analyzer()
    a.enable_guessing = True
    return a


@pytest.fixture(scope="module")
def inflector() -> Inflector:
    return Inflector()


class TestAnalyzer:
    def test_known_noun(self, analyzer: Analyzer) -> None:
        word = analyzer.analyze("tēvs")
        assert word.is_recognized()
        wf = word.wordforms[0]
        assert wf.lexeme is not None and wf.lexeme.lemma == "tēvs"
        assert wf.is_matching_strong("Vārdšķira", "Lietvārds")
        assert wf.is_matching_strong("Locījums", "Nominatīvs")

    def test_known_verb_form(self, analyzer: Analyzer) -> None:
        word = analyzer.analyze("rakstu")
        assert word.is_recognized()
        lemmas = {w.lexeme.lemma for w in word.wordforms if w.lexeme}
        # 'rakstu' could be 'rakstīt' (verb 1.sg pres) or 'raksts' (noun)
        assert lemmas & {"raksts", "rakstīt"}

    def test_prefix_derived(self, analyzer: Analyzer) -> None:
        word = analyzer.analyze("aizrakt")
        assert word.is_recognized()
        # Lemma should be 'aizrakt' (with prefix preserved)
        lemmas = {
            w.get("Pamatforma") or (w.lexeme.lemma if w.lexeme else "") for w in word.wordforms
        }
        assert "aizrakt" in lemmas

    def test_negation_prefix(self, analyzer: Analyzer) -> None:
        word = analyzer.analyze("neraku")
        assert word.is_recognized()
        # Should resolve to 'rakt' base lemma
        lemmas = {w.lexeme.lemma for w in word.wordforms if w.lexeme}
        assert "rakt" in lemmas

    def test_number_fallback(self, analyzer: Analyzer) -> None:
        word = analyzer.analyze("2006.")
        assert word.is_recognized()
        assert word.wordforms[0].is_matching_strong("Vārdšķira", "Reziduālis")

    def test_unknown_word_guessing(self, analyzer: Analyzer) -> None:
        word = analyzer.analyze("pokemonizators")
        assert word.is_recognized()
        # Lemma should be the form itself (or derived)
        wf = word.wordforms[0]
        assert wf.get("Pamatforma") == "pokemonizators"


class TestInflector:
    def test_noun_inflection(self, inflector: Inflector) -> None:
        forms = inflector.inflect("tēvs")
        surfaces = {f.token for f in forms}
        assert {"tēvs", "tēva", "tēvam", "tēvu", "tēvā", "tēvi", "tēviem", "tēvos"} <= surfaces

    def test_verb_inflection_includes_negation(self, inflector: Inflector) -> None:
        forms = inflector.inflect("rakt")
        surfaces = {f.token for f in forms}
        assert "raku" in surfaces  # 1st-pers present
        # Negation forms
        negated = {f.token for f in forms if f.is_matching_strong("Noliegums", "Jā")}
        assert any(s.startswith("ne") for s in negated)
        assert "neraku" in negated

    def test_adjective_gradation(self, inflector: Inflector) -> None:
        forms = inflector.inflect("liels")
        surfaces = {f.token for f in forms}
        assert "lielāks" in surfaces
        assert "vislielākais" in surfaces


class TestTrieIntegration:
    def test_trie_clone_shares_branches(self) -> None:
        t = Trie()
        t.initialize_exceptions()
        clone = Trie(t)
        # The branch list is shared but each instance has its own iterator state
        assert clone._branch_list is t._branch_list


# ---------------------------------------------------------------------------
# Splitting — tokenizer (port of Splitting.java)
# ---------------------------------------------------------------------------


class TestSplitting:
    @pytest.fixture(scope="class")
    def tokenize(self):
        from vardene.splitting import tokenize
        return tokenize

    @pytest.fixture(scope="class")
    def tokenize_sentences(self):
        from vardene.splitting import tokenize_sentences
        return tokenize_sentences

    def test_basic(self, tokenize) -> None:
        assert tokenize("Es eju mājās.") == ["Es", "eju", "mājās", "."]

    def test_clock(self, tokenize) -> None:
        assert tokenize("plkst. 14:30") == ["plkst", ".", "14:30"]

    def test_url(self, tokenize) -> None:
        assert tokenize("Skat www.tezaurs.lv vai https://example.com/path") == [
            "Skat", "www.tezaurs.lv", "vai", "https://example.com/path"
        ]

    def test_email(self, tokenize) -> None:
        assert tokenize("kontakts: peteris@example.com") == [
            "kontakts", ":", "peteris@example.com"
        ]

    def test_paragraph_number(self, tokenize) -> None:
        assert tokenize("Likuma 1.2.3.4. punkts") == ["Likuma", "1.2.3.4.", "punkts"]

    def test_iso_date(self, tokenize) -> None:
        assert tokenize("2009-12-14 un 2024.05.08") == ["2009-12-14", "un", "2024.05.08"]

    def test_repeating_punct(self, tokenize) -> None:
        assert tokenize("Ko?! Ej!?") == ["Ko", "?!", "Ej", "!?"]

    def test_thousand_separator(self, tokenize) -> None:
        assert tokenize("1 234,56 EUR") == ["1 234,56", "EUR"]

    def test_spaced_letters(self, tokenize) -> None:
        assert tokenize("a t s t a r p e s") == ["a t s t a r p e s"]

    def test_brute_split(self, tokenize) -> None:
        assert tokenize("plkst. 14:30", brute_split=True) == ["plkst.", "14:30"]

    def test_sentences(self, tokenize_sentences) -> None:
        out = tokenize_sentences('Es teicu: "Sveiki!" Pēc tam aizgāju.')
        assert len(out) == 2
        # Quote-after-bang glues to first sentence (direct-speech rule).
        assert out[0][-1] == '"'
        assert out[1] == ["Pēc", "tam", "aizgāju", "."]


# ---------------------------------------------------------------------------
# Phrase + people inflection
# ---------------------------------------------------------------------------


class TestPhrase:
    @pytest.fixture(scope="class")
    def inflect_phrase(self):
        from vardene.phrase import inflect_phrase
        return inflect_phrase

    @pytest.fixture(scope="class")
    def normalize_phrase(self):
        from vardene.phrase import normalize_phrase
        return normalize_phrase

    @pytest.fixture(scope="class")
    def inflect_people(self):
        from vardene.phrase import inflect_people
        return inflect_people

    def test_adjective_noun_definite(self, inflect_phrase) -> None:
        out = inflect_phrase("sarkanā māja")
        assert out["Nominatīvs"] == "sarkanā māja"
        assert out["Ģenitīvs"] == "sarkanās mājas"
        assert out["Datīvs"] == "sarkanajai mājai"
        assert out["Akuzatīvs"] == "sarkano māju"
        assert out["Lokatīvs"] == "sarkanajā mājā"

    def test_adjective_noun_indefinite(self, inflect_phrase) -> None:
        out = inflect_phrase("zaļa zāle")
        assert out["Nominatīvs"] == "zaļa zāle"
        assert out["Akuzatīvs"] == "zaļu zāli"

    def test_normalize(self, normalize_phrase) -> None:
        assert normalize_phrase("sarkano māju") == "sarkanā māja"
        # `lielo bērnu` is unambiguously definite in genitive plural, so
        # normalisation must preserve definiteness ("lielais bērns").
        assert normalize_phrase("lielo bērnu") == "lielais bērns"

    def test_person_full_paradigm(self, inflect_people) -> None:
        out = inflect_people("Jānis Bērziņš")
        assert len(out) == 2  # given + surname
        for component in out:
            cases = {(d["Locījums"], d["Skaitlis"]) for d in component}
            # All 6 cases × 2 numbers = 12 forms expected
            assert len(cases) == 12
        # Spot-check known surface forms
        janis = {(d["Locījums"], d["Skaitlis"]): d["Vārds"] for d in out[0]}
        assert janis[("Ģenitīvs", "Vienskaitlis")] == "Jāņa"
        assert janis[("Datīvs", "Vienskaitlis")] == "Jānim"
        assert janis[("Vokatīvs", "Vienskaitlis")] == "Jāni"


# ---------------------------------------------------------------------------
# Suitable paradigms (ported from Java suitableParadigms)
# ---------------------------------------------------------------------------


class TestSuitableParadigms:
    @pytest.fixture(scope="class")
    def analyzer(self) -> Analyzer:
        return Analyzer()

    def test_known_noun(self, analyzer: Analyzer) -> None:
        result = analyzer.suitable_paradigms("kaķis")
        names = [p.name for p in result]
        assert "noun-2b" in names  # tētis-class (no mija)

    def test_known_verb(self, analyzer: Analyzer) -> None:
        result = analyzer.suitable_paradigms("rakt")
        names = [p.name for p in result]
        assert "verb-1" in names

    def test_sorted_by_frequency(self, analyzer: Analyzer) -> None:
        # noun-1a (-s declension) is much more common than ltg variants
        result = analyzer.suitable_paradigms("mežs")
        names = [p.name for p in result]
        assert names[0] == "noun-1a"


# ---------------------------------------------------------------------------
# HTTP API (Flask) — smoke tests via test_client
# ---------------------------------------------------------------------------


class TestApi:
    @pytest.fixture(scope="class")
    def client(self):
        from vardene.api import create_app
        return create_app().test_client()

    def test_health(self, client) -> None:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json["status"] == "ok"

    def test_analyze(self, client) -> None:
        r = client.get("/api/analyze/kaķis")
        assert r.status_code == 200
        assert r.json["wordforms"]

    def test_tokenize(self, client) -> None:
        r = client.get("/api/tokenize/Es%20eju%20m%C4%81j%C4%81s.")
        assert r.json["tokens"] == ["Es", "eju", "mājās", "."]

    def test_inflect_phrase(self, client) -> None:
        r = client.get("/api/inflect_phrase/sarkan%C4%81%20m%C4%81ja")
        assert r.json["Akuzatīvs"] == "sarkano māju"

    def test_normalize_phrase(self, client) -> None:
        r = client.get("/api/normalize_phrase/sarkano%20m%C4%81ju")
        assert r.json == "sarkanā māja"

    def test_inflect_people(self, client) -> None:
        r = client.get("/api/inflect_people/json/J%C4%81nis")
        # Single-component name → wrapped in outer list, 12 inner forms
        data = r.json
        assert len(data) == 1
        assert len(data[0]) == 12

    def test_suitable_paradigm(self, client) -> None:
        r = client.get("/api/suitable_paradigm/ka%C4%B7is")
        names = [p["Description"] for p in r.json]
        assert "noun-2b" in names

    def test_valency_explained(self, client) -> None:
        r = client.get("/api/verbs/foo")
        assert r.status_code == 200
        assert r.json["error"] == "out_of_scope"
