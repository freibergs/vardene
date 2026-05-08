"""Flask app exposing the morphology engine over HTTP.

Implemented routes (parity with `api.vardene.lv` Java service where the
underlying engine supports it):

  GET  /api/analyze/<word>                          single-word analysis (LV attrs)
  GET  /api/analyze/en/<word>                       same with English attrs
  GET  /api/analyzesentence/<query>                 sentence-level analysis
  GET  /api/tokenize/<query>                        whitespace+punctuation tokenizer
  POST /api/tokenize                                same, body = {"text": ...}
  GET  /api/v1/inflections/<query>                  all forms of a lemma
  GET  /api/v1/inflections/<query>?paradigm=NAME    forms with explicit paradigm
  GET  /api/v1/inflections/<query>?paradigm&stem1=&stem2=&stem3=
                                                    forms for a verb-1 with explicit stems
  GET  /api/inflect/json/<query>                    same as v1/inflections, format selector
  GET  /api/inflect/json/<lang>/<query>             with language filter (lv / ltg)
  GET  /api/morphotagger/<query>                    sentence-level disambiguation
  GET  /api/suitable_paradigm/<lemma>               paradigms that could generate `lemma`
  GET  /api/inflect_phrase/<phrase>                 phrase declension table
  GET  /api/normalize_phrase/<phrase>               lemmatised (Nominatīvs) phrase
  GET  /api/inflect_people/json/<name>              full declension of a personal name
  GET  /api/health                                  liveness probe

Out of scope (return a 200 explaining why, not 501):
  /api/verbs, /api/neverbs                          valency frames live in a
                                                    separate non-open service
"""

from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from vardene.analyzer import Analyzer
from vardene.api.serialization import wordform_to_dict
from vardene.inflector import Inflector
from vardene.phrase import inflect_people, inflect_phrase, normalize_phrase
from vardene.splitting import tokenize as _tokenize
from vardene.splitting import tokenize_sentences as _tokenize_sentences


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    # Match api.tezaurs.lv: emit raw UTF-8 instead of \u-escaping non-ASCII.
    # Flask 3+ uses `app.json` provider with `ensure_ascii` flag; setting it
    # before the first request takes effect for all `jsonify` calls.
    app.json.ensure_ascii = False  # type: ignore[attr-defined]
    app.config["JSON_AS_ASCII"] = False  # legacy fallback
    analyzer = Analyzer()
    # api.tezaurs.lv runs with guessing ON for /morphotagger and friends — out-of-
    # lexicon words like proper-noun diminutives (`māmīņa`) get a backed-off
    # guess instead of a null reading. Match that.
    analyzer.enable_guessing = True
    inflector = Inflector(lexicon=analyzer.lexicon)

    # ----- frontend ----------------------------------------------------------

    @app.route("/")
    def index():
        return render_template("index.html")

    # ----- analysis ---------------------------------------------------------

    def _filter_proper_for_lowercase(word, wordforms):
        """If the query is all-lowercase, drop Īpašvārds (proper-noun) readings.
        Matches `api.tezaurs.lv` behaviour: lowercase `rakstu` returns 3
        readings, not the 4 our engine produces (the extra one is `Raksti`,
        a place-name, which the user clearly did not mean)."""
        if word != word.lower():
            return list(wordforms)
        return [
            wf for wf in wordforms
            if not wf.is_matching_strong("Lietvārda tips", "Īpašvārds")
        ]

    @app.route("/api/analyze/<word>")
    def analyze_word(word: str):
        result = analyzer.analyze(word)
        wfs = _filter_proper_for_lowercase(word, result.wordforms)
        return jsonify({
            "word": word,
            "wordforms": [wordform_to_dict(wf) for wf in wfs],
        })

    @app.route("/api/analyze/en/<word>")
    def analyze_word_en(word: str):
        result = analyzer.analyze(word)
        wfs = _filter_proper_for_lowercase(word, result.wordforms)
        return jsonify({
            "word": word,
            "wordforms": [wordform_to_dict(wf, language="en") for wf in wfs],
        })

    @app.route("/api/analyzesentence/<path:query>")
    def analyze_sentence(query: str):
        tokens = _tokenize(query)
        results = analyzer.analyze_sentence(tokens)
        return jsonify(
            {
                "query": query,
                "tokens": [
                    {
                        "token": tok,
                        "wordforms": [wordform_to_dict(wf) for wf in r.wordforms],
                    }
                    for tok, r in zip(tokens, results, strict=True)
                ],
            }
        )

    # ----- tokenization -----------------------------------------------------

    @app.route("/api/tokenize/<path:query>")
    def tokenize_get(query: str):
        return jsonify({"query": query, "tokens": _tokenize(query)})

    @app.route("/api/tokenize", methods=["POST"])
    def tokenize_post():
        body = request.get_json(silent=True) or {}
        text = body.get("text", "")
        return jsonify({"query": text, "tokens": _tokenize(text)})

    # ----- inflection -------------------------------------------------------

    def _inflect_response(query: str, language: str = "lv"):
        paradigm = request.args.get("paradigm")
        stem1 = request.args.get("stem1")
        stem2 = request.args.get("stem2")
        stem3 = request.args.get("stem3")
        if paradigm is not None:
            attrs: dict[str, str] = {}
            if stem1 or stem2 or stem3:
                # Verb-1 explicit stems — populate via paradigm-typed inflection.
                if stem1:
                    attrs["stem1"] = stem1
                if stem2:
                    attrs["stem2"] = stem2
                if stem3:
                    attrs["stem3"] = stem3
            forms = inflector.inflect_from_paradigm(query, paradigm, attrs)
        else:
            forms = inflector.inflect(query)
        # Optional language filter (LV vs LTG).
        if language and language != "lv":
            forms = [
                f
                for f in forms
                if f.ending and f.ending.paradigm and f.ending.paradigm.language == language
            ]
        elif language == "lv":
            forms = [
                f
                for f in forms
                if not (f.ending and f.ending.paradigm and f.ending.paradigm.language == "ltg")
            ]
        return jsonify(
            {
                "lemma": query,
                "paradigm": paradigm,
                "language": language,
                "forms": [wordform_to_dict(f) for f in forms],
            }
        )

    @app.route("/api/v1/inflections/<query>")
    def inflections_v1(query: str):
        return _inflect_response(query)

    @app.route("/api/inflect/<fmt>/<query>")
    def inflect_fmt(fmt: str, query: str):
        if fmt != "json":
            return jsonify({"error": "unsupported_format", "supported": ["json"]}), 400
        return _inflect_response(query)

    @app.route("/api/inflect/<fmt>/<lang>/<query>")
    def inflect_fmt_lang(fmt: str, lang: str, query: str):
        if fmt != "json":
            return jsonify({"error": "unsupported_format", "supported": ["json"]}), 400
        return _inflect_response(query, language=lang)

    # ----- disambiguator (statistical morphological tagger) -----------------

    @app.route("/api/morphotagger/<path:query>")
    def morphotagger(query: str):
        tokens = _tokenize(query)
        results = analyzer.analyze_sentence(tokens)
        return jsonify(
            {
                "query": query,
                "tokens": [
                    {
                        "token": tok,
                        "best": (wordform_to_dict(r.wordforms[0]) if r.wordforms else None),
                    }
                    for tok, r in zip(tokens, results, strict=True)
                ],
            }
        )

    # ----- paradigm + multi-word inflection ---------------------------------

    @app.route("/api/suitable_paradigm/<lemma>")
    def suitable_paradigm_route(lemma: str):
        paradigms = analyzer.suitable_paradigms(lemma)
        only_lv = request.args.get("language", "lv") == "lv"
        if only_lv:
            paradigms = [p for p in paradigms if p.language != "ltg"]
        return jsonify(
            [{"ID": p.id, "Description": p.name} for p in paradigms]
        )

    @app.route("/api/inflect_phrase/<path:phrase>")
    def inflect_phrase_route(phrase: str):
        return jsonify(inflect_phrase(phrase, analyzer=analyzer, inflector=inflector))

    @app.route("/api/normalize_phrase/<path:phrase>")
    def normalize_phrase_route(phrase: str):
        return jsonify(normalize_phrase(phrase, analyzer=analyzer, inflector=inflector))

    @app.route("/api/inflect_people/json/<path:query>")
    def inflect_people_route(query: str):
        return jsonify(inflect_people(query, analyzer=analyzer, inflector=inflector))

    # ----- valency lookups (NOT in upstream open-source morphology) ---------
    # api.tezaurs.lv `/verbs` and `/neverbs` proxy a separate valency lexicon
    # (see https://github.com/PeterisP/morphology — not present in that repo).
    # We expose the documented response shape with an explanatory note.

    @app.route("/api/verbs/<path:query>")
    @app.route("/api/neverbs/<path:query>")
    def valency(query: str):
        return jsonify(
            {
                "error": "out_of_scope",
                "message": (
                    "Valency frames live in a separate non-open-source service "
                    "layer at api.tezaurs.lv. The vardene engine intentionally "
                    "scopes to the morphology library and does not bundle "
                    "valency data."
                ),
                "tags": ["Nom", "Gen", "Dat", "Acc", "Loc", "V1", "V2", "V3",
                         "Inf", "S", "TR", "Adv"],
            }
        )

    # ----- meta -------------------------------------------------------------

    @app.route("/api/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "engine": "vardene",
                "lexicon_size": len(analyzer.lexicon.table),
            }
        )

    return app
