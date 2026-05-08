"""Flask app exposing the morphology engine over HTTP.

Implemented routes (parity with `api.tezaurs.lv` Java service where the
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
  GET  /api/health                                  liveness probe

Placeholders (501 Not Implemented; will be filled in once the upstream
modules they wrap are ported):
  /api/verbs, /api/neverbs, /api/suitable_paradigm,
  /api/inflect_people, /api/inflect_phrase, /api/normalize_phrase
"""

from __future__ import annotations

import re
from typing import Any

from flask import Flask, jsonify, render_template, request

from tezaurs.analyzer import Analyzer
from tezaurs.api.serialization import wordform_to_dict
from tezaurs.inflector import Inflector

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Lightweight whitespace + punctuation tokenizer.

    A direct port of Java's `Splitting.java` (with its 12 hardcoded automata
    for clocks/dates/URLs/etc.) is pending — this is the simple regex
    fallback in the meantime.
    """
    return _TOKEN_RE.findall(text)


def _not_implemented(name: str, plan: str) -> Any:
    return (
        jsonify(
            {
                "error": "not_implemented",
                "endpoint": name,
                "message": (
                    f"This endpoint requires a port that has not yet been completed. Status: {plan}"
                ),
            }
        ),
        501,
    )


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    analyzer = Analyzer()
    analyzer.enable_guessing = False  # match Java default (guessing off by default)
    inflector = Inflector(lexicon=analyzer.lexicon)

    # ----- frontend ----------------------------------------------------------

    @app.route("/")
    def index():
        return render_template("index.html")

    # ----- analysis ---------------------------------------------------------

    @app.route("/api/analyze/<word>")
    def analyze_word(word: str):
        result = analyzer.analyze(word)
        return jsonify(
            {
                "word": word,
                "wordforms": [wordform_to_dict(wf) for wf in result.wordforms],
            }
        )

    @app.route("/api/analyze/en/<word>")
    def analyze_word_en(word: str):
        result = analyzer.analyze(word)
        return jsonify(
            {
                "word": word,
                "wordforms": [wordform_to_dict(wf, language="en") for wf in result.wordforms],
            }
        )

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

    # ----- placeholders (501 until upstream module is ported) ---------------

    @app.route("/api/verbs/<path:query>")
    def verbs(query: str):
        return _not_implemented(
            "verbs", "external valency annotation tool, not in upstream morphology repo"
        )

    @app.route("/api/neverbs/<path:query>")
    def neverbs(query: str):
        return _not_implemented(
            "neverbs", "external valency annotation tool, not in upstream morphology repo"
        )

    @app.route("/api/suitable_paradigm/<lemma>")
    def suitable_paradigm(lemma: str):
        return _not_implemented("suitable_paradigm", "paradigm suitability scorer pending port")

    @app.route("/api/inflect_people/json/<path:query>")
    def inflect_people(query: str):
        return _not_implemented(
            "inflect_people", "person-name inflector pending port (PersonInflector.java)"
        )

    @app.route("/api/inflect_phrase/<path:phrase>")
    def inflect_phrase(phrase: str):
        return _not_implemented("inflect_phrase", "multi-word entity inflection pending port")

    @app.route("/api/normalize_phrase/<path:phrase>")
    def normalize_phrase(phrase: str):
        return _not_implemented("normalize_phrase", "multi-word entity normalisation pending port")

    # ----- meta -------------------------------------------------------------

    @app.route("/api/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "engine": "tezaurs",
                "lexicon_size": len(analyzer.lexicon.table),
            }
        )

    return app
