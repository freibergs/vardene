"""Hierarchical sentence-level disambiguator (3 levels).

Stage 1 — POS CRF (`crf_pos.crfsuite`, 13 classes): predicts POS char from
sentence context. Resolves the biggest gap (noun/verb confusion).

Stage 2 — 4-char subtag CRF (`crf_subtag.crfsuite`, 166 classes): predicts
the first 4 tag chars (POS + first 3 features). Sequence-aware.

Stage 3 — Per-POS classifier (`per_pos_clf.pkl`): for each POS, a sklearn
LogisticRegression that predicts the FULL tag from per-token features.
Per-POS class space is small (50-300 tags), which keeps training fast and
inference accurate.

Promotion strategy at runtime:
  1. Predict per-token: POS, 4-char subtag, full tag.
  2. Try to find the wordform whose tag matches the full prediction.
  3. Back off: 4-char prefix → POS-only → original ranking.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import ClassVar

from tezaurs.markup import to_tag
from tezaurs.wordform import Word


class _SparseLRClassifier:
    """Drop-in replacement for sklearn LogisticRegression that stores its
    coefficient matrix as scipy CSR. Implements the small predict surface
    that `tag_sentence` exercises (`predict_log_proba`, `classes_`).

    Expected ~15× memory reduction vs dense float32 LR with negligible
    accuracy impact when the threshold is tuned (we keep |coef| ≥ 0.01).
    """

    __slots__ = ("classes_", "_coef_sparse", "_intercept", "_n_classes")

    def __init__(self, classes_, intercept, coef_sparse) -> None:
        self.classes_ = classes_
        self._intercept = intercept
        self._coef_sparse = coef_sparse  # CSR (n_classes, n_features)
        self._n_classes = len(classes_)

    def predict_log_proba(self, X) -> "object":
        # X: (n_samples, n_features) sparse — output of DictVectorizer
        import numpy as np
        from scipy.special import logsumexp

        # decision = X @ W.T + b
        scores = X @ self._coef_sparse.T  # sparse × sparse → CSR
        scores = scores.toarray() if hasattr(scores, "toarray") else np.asarray(scores)
        scores += self._intercept

        # sklearn binary LR convention: coef_ has shape (1, F) but classes_
        # has 2 entries. predict_log_proba returns (n_samples, 2) where
        # column 0 = log P(neg), column 1 = log P(pos). We replicate that.
        if scores.shape[1] == 1 and self._n_classes == 2:
            log_p1 = -np.logaddexp(0, -scores)  # log(sigmoid(s))
            log_p0 = -np.logaddexp(0, scores)   # log(1 - sigmoid(s))
            return np.hstack([log_p0, log_p1])

        # Multiclass: log-softmax along class axis.
        log_z = logsumexp(scores, axis=1, keepdims=True)
        return scores - log_z


def _wrap_sparse_models(sparse_dict):
    """Convert a dict of {pos: {coef_sparse, classes_, intercept_, vec}} into
    the (vec, classifier) tuples that the rest of the tagger expects."""
    wrapped = {}
    for pos, payload in sparse_dict.items():
        clf = _SparseLRClassifier(
            classes_=payload["classes_"],
            intercept=payload["intercept_"],
            coef_sparse=payload["coef_sparse"],
        )
        wrapped[pos] = (payload["vec"], clf)
    return wrapped


def _word_shape(word: str) -> str:
    """Stanford `dan2useLC`-equivalent — must match the trainer's encoding."""
    out: list[str] = []
    for c in word:
        if c.isupper():
            t = "X"
        elif c.islower():
            t = "x"
        elif c.isdigit():
            t = "9"
        else:
            t = "."
        if out and out[-1] == t:
            continue
        out.append(t)
    return "".join(out)


class CRFTagger:
    """Sentence-level CRF disambiguator. Lazy-loads two models:
      - `crf_pos.crfsuite` — POS char (13 classes)
      - `crf_subtag.crfsuite` — first 4 chars (166 classes; POS + first 3 features)

    Promotion strategy: prefer wordform whose tag exactly matches the predicted
    subtag prefix; fall back to POS-only match; otherwise keep original ranking.
    """

    _POS_MODEL_NAME: ClassVar[str] = "crf_pos.crfsuite"
    _SUBTAG_MODEL_NAME: ClassVar[str] = "crf_subtag.crfsuite"
    _PER_POS_MODEL_NAME: ClassVar[str] = "per_pos_clf.pkl"
    _BIGRAM_MODEL_NAME: ClassVar[str] = "tag_bigrams.json"
    _instance: ClassVar[CRFTagger | None] = None

    __slots__ = ("_pos_crf", "_subtag_crf", "_subtag_len", "_per_pos_clf", "_bigrams")

    def __init__(self, pos_crf, subtag_crf, subtag_len: int, per_pos_clf=None, bigrams=None) -> None:
        self._pos_crf = pos_crf
        self._subtag_crf = subtag_crf
        self._subtag_len = subtag_len
        # dict[pos_char, (DictVectorizer, LogisticRegression)] for full-tag prediction
        self._per_pos_clf = per_pos_clf or {}
        # dict[prev_state, dict[cur_state, log_prob]] for tag-bigram transitions.
        # State = first 4 chars of the tag.
        self._bigrams: dict[str, dict[str, float]] = bigrams or {}

    @classmethod
    def load(cls) -> CRFTagger | None:
        try:
            import sklearn_crfsuite  # noqa: F401
        except ImportError:
            return None
        pos_path = cls._model_path(cls._POS_MODEL_NAME)
        subtag_path = cls._model_path(cls._SUBTAG_MODEL_NAME)
        per_pos_path = cls._model_path(cls._PER_POS_MODEL_NAME)
        if not pos_path.exists():
            return None
        import sklearn_crfsuite

        pos_crf = sklearn_crfsuite.CRF(model_filename=str(pos_path))
        subtag_crf = (
            sklearn_crfsuite.CRF(model_filename=str(subtag_path))
            if subtag_path.exists()
            else None
        )
        per_pos_clf: dict = {}
        if per_pos_path.exists():
            import pickle
            with per_pos_path.open("rb") as f:
                per_pos_clf = pickle.load(f)
            # Detect format: sparse-format dicts have 'coef_sparse' key.
            sample = next(iter(per_pos_clf.values()), None)
            if isinstance(sample, dict) and "coef_sparse" in sample:
                per_pos_clf = _wrap_sparse_models(per_pos_clf)
        bigrams_path = cls._model_path(cls._BIGRAM_MODEL_NAME)
        bigrams: dict[str, dict[str, float]] = {}
        if bigrams_path.exists():
            import json as _json
            with bigrams_path.open(encoding="utf-8") as f:
                bigrams = _json.load(f)
        return cls(pos_crf, subtag_crf, subtag_len=4, per_pos_clf=per_pos_clf, bigrams=bigrams)

    @classmethod
    def instance(cls) -> CRFTagger | None:
        if cls._instance is None:
            loaded = cls.load()
            if loaded is None:
                return None
            cls._instance = loaded
        return cls._instance

    @classmethod
    def _model_path(cls, name: str) -> Path:
        return Path(str(files("tezaurs").joinpath("data", name)))

    # --- inference -----------------------------------------------------

    def predict_pos(self, words: list[str]) -> list[str]:
        """POS char per token (`n/v/a/p/r/s/c/m/i/y/q/z/x`)."""
        if not words:
            return []
        feats = [_token_features(words, i) for i in range(len(words))]
        return self._pos_crf.predict_single(feats)

    def predict_subtag(self, words: list[str]) -> list[str] | None:
        """First-N tag chars per token, or None if subtag model isn't loaded."""
        if not words or self._subtag_crf is None:
            return None
        feats = [_token_features(words, i) for i in range(len(words))]
        return self._subtag_crf.predict_single(feats)

    def tag_sentence(self, sentence_words: list[Word]) -> list[Word]:
        """Re-rank each Word's wordforms via lattice rescoring.

        For each token:
          1. Get POS prediction (CRF-based, sentence-aware).
          2. Get full distribution over all in-POS tags from the LR classifier.
          3. Score every candidate wordform by `log P(candidate_tag | features)`.
             Wordforms whose tag isn't in the classifier's class set fall back
             to the subtag prefix or POS-only score.
          4. Promote the highest-scoring wordform.

        Classifier calls are batched per POS — one `predict_log_proba` invocation
        covers every token in that POS bucket instead of N separate calls.
        """
        if not sentence_words:
            return sentence_words
        words_list = [w.token for w in sentence_words]
        pos_seq = self.predict_pos(words_list)
        subtag_seq = self.predict_subtag(words_list)
        token_feats = [_token_features(words_list, i) for i in range(len(words_list))]

        # Bucket tokens by predicted POS, then run one batched
        # predict_log_proba per bucket. Skip tokens that have only one
        # wordform candidate — there's nothing to rescore.
        tag_distributions: list[dict[str, float] | None] = [None] * len(sentence_words)
        buckets: dict[str, list[int]] = {}
        for idx, pos in enumerate(pos_seq):
            wfs = sentence_words[idx].wordforms
            if len(wfs) <= 1:
                continue
            buckets.setdefault(pos, []).append(idx)
        for pos, indices in buckets.items():
            entry = self._per_pos_clf.get(pos)
            if entry is None:
                continue
            vec, clf = entry
            X = vec.transform([token_feats[i] for i in indices])
            log_probs = clf.predict_log_proba(X)
            classes = clf.classes_
            for row_idx, token_idx in enumerate(indices):
                tag_distributions[token_idx] = dict(
                    zip(classes, log_probs[row_idx], strict=True)
                )

        if self._bigrams:
            self._viterbi_rescore(sentence_words, pos_seq, subtag_seq, tag_distributions)
        else:
            for idx, word in enumerate(sentence_words):
                if not word.wordforms:
                    continue
                target_pos = pos_seq[idx]
                target_subtag = subtag_seq[idx] if subtag_seq else None
                self._rescore(word, target_pos, target_subtag, tag_distributions[idx])
        return sentence_words

    def _viterbi_rescore(
        self,
        sentence_words: list[Word],
        pos_seq: list[str],
        subtag_seq: list[str] | None,
        tag_distributions: list[dict[str, float] | None],
    ) -> None:
        """Pick the joint-best wordform sequence using:
          - emission score: classifier log-prob of the wordform's tag
          - transition score: bigram log-prob between consecutive 4-char states

        Limits each token to its top 8 candidate wordforms by emission score
        to keep the lattice small. Recovers the best path with backpointers.
        """
        from tezaurs.markup import to_tag

        TRANS_WEIGHT = 0.08  # tuned on 200-sentence sample (0.05/0.10 gave less)
        BEAM = 8

        n = len(sentence_words)
        candidates: list[list[tuple[int, str, float]]] = []
        for idx, word in enumerate(sentence_words):
            if not word.wordforms:
                candidates.append([])
                continue
            target_pos = pos_seq[idx]
            target_subtag = subtag_seq[idx] if subtag_seq else None
            dist = tag_distributions[idx]
            scored: list[tuple[int, str, float]] = []
            for i, wf in enumerate(word.wordforms):
                tag = to_tag(wf)
                if not tag or tag == "-":
                    continue
                if dist is not None and tag in dist:
                    s = dist[tag]
                elif target_subtag and tag.startswith(target_subtag):
                    s = -10.0 + len(target_subtag) * 0.1
                elif tag[:1] == target_pos:
                    s = -100.0
                else:
                    s = -1000.0
                scored.append((i, tag, s))
            scored.sort(key=lambda x: -x[2])
            candidates.append(scored[:BEAM])

        # Forward Viterbi.
        prev_states: list[dict[int, tuple[float, int]]] = []  # idx_in_cands → (score, prev_idx_in_cands)
        for t in range(n):
            cur: dict[int, tuple[float, int]] = {}
            cands = candidates[t]
            if not cands:
                prev_states.append({})
                continue
            if t == 0:
                for j, (_, tag, emis) in enumerate(cands):
                    state = tag[:4]
                    bonus = self._trans_score("<s>", state) * TRANS_WEIGHT
                    cur[j] = (emis + bonus, -1)
            else:
                prev = prev_states[-1]
                if not prev:
                    for j, (_, tag, emis) in enumerate(cands):
                        cur[j] = (emis, -1)
                else:
                    for j, (_, tag, emis) in enumerate(cands):
                        state = tag[:4]
                        best_score = -1e18
                        best_prev = -1
                        for pj, (p_score, _) in prev.items():
                            p_tag = candidates[t - 1][pj][1]
                            trans = self._trans_score(p_tag[:4], state) * TRANS_WEIGHT
                            tot = p_score + trans + emis
                            if tot > best_score:
                                best_score = tot
                                best_prev = pj
                        cur[j] = (best_score, best_prev)
            prev_states.append(cur)

        # Backtrack the best path. Skips tokens that had no candidates.
        path: list[int] = [-1] * n
        # Find last non-empty position to start.
        last_t = next((t for t in range(n - 1, -1, -1) if prev_states[t]), -1)
        if last_t >= 0:
            last = max(prev_states[last_t].items(), key=lambda kv: kv[1][0])
            path[last_t] = last[0]
            for t in range(last_t, 0, -1):
                if path[t] not in prev_states[t]:
                    break
                _, prev_idx = prev_states[t][path[t]]
                if prev_idx < 0:
                    # Best path starts at t — earlier tokens use independent best.
                    for u in range(t - 1, -1, -1):
                        if prev_states[u]:
                            path[u] = max(
                                prev_states[u].items(), key=lambda kv: kv[1][0]
                            )[0]
                    break
                path[t - 1] = prev_idx

        # Promote winning wordform per token.
        for t, word in enumerate(sentence_words):
            if not word.wordforms or path[t] < 0:
                continue
            cands = candidates[t]
            if path[t] >= len(cands):
                continue
            wf_idx = cands[path[t]][0]
            if wf_idx == 0:
                continue
            best = word.wordforms[wf_idx]
            word.wordforms = [best] + [
                w for j, w in enumerate(word.wordforms) if j != wf_idx
            ]

    def _trans_score(self, prev_state: str, cur_state: str) -> float:
        row = self._bigrams.get(prev_state)
        if row is None:
            row = self._bigrams.get("<DEFAULT>")
            if row is None:
                return -10.0
        score = row.get(cur_state)
        if score is None:
            default_row = self._bigrams.get("<DEFAULT>")
            if default_row is not None:
                score = default_row.get(cur_state, -10.0)
            else:
                score = -10.0
        return score

    def tag_word(self, word: Word, *, prev: str | None = None, nxt: str | None = None) -> Word:
        """Single-word disambiguation with lattice rescoring."""
        words = [word.token]
        idx = 0
        if prev:
            words.insert(0, prev)
            idx = 1
        if nxt:
            words.append(nxt)
        pos_seq = self.predict_pos(words)
        subtag_seq = self.predict_subtag(words)
        token_feats = [_token_features(words, i) for i in range(len(words))]
        target_pos = pos_seq[idx]
        target_subtag = subtag_seq[idx] if subtag_seq else None
        tag_distribution = self.score_full_tag(target_pos, token_feats[idx])
        self._rescore(word, target_pos, target_subtag, tag_distribution)
        return word

    def _rescore(
        self,
        word: Word,
        target_pos: str,
        target_subtag: str | None,
        tag_distribution: dict[str, float] | None,
    ) -> None:
        """Pick the wordform with the highest classifier score, with backoff
        to subtag prefix / POS-only matching when the classifier isn't loaded
        or doesn't know the candidate tag."""
        from tezaurs.markup import to_tag

        wordforms = word.wordforms
        if not wordforms:
            return

        scores: list[tuple[float, int]] = []  # (score, original_index)
        for i, wf in enumerate(wordforms):
            tag = to_tag(wf)
            score = -1e9
            if tag and tag != "-":
                # Tier 1: classifier log-probability for this exact tag.
                if tag_distribution is not None and tag in tag_distribution:
                    score = tag_distribution[tag]
                # Tier 2: subtag prefix match (linear bonus by prefix length).
                elif target_subtag and tag.startswith(target_subtag):
                    score = -10 + len(target_subtag) * 0.1
                # Tier 3: POS match.
                elif tag[:1] == target_pos:
                    score = -100
                # Tier 4: any candidate (better than nothing).
                else:
                    score = -1000
            scores.append((score, i))

        # Stable sort by score desc, then original index asc (preserves the
        # original ranking among tied scores).
        scores.sort(key=lambda x: (-x[0], x[1]))
        best_idx = scores[0][1]
        if best_idx != 0:
            best = wordforms[best_idx]
            word.wordforms = [best] + [w for j, w in enumerate(wordforms) if j != best_idx]

    # Kept as legacy fallback path, currently unused.
    def _promote(
        self,
        word: Word,
        target_pos: str,
        target_subtag: str | None,
        target_full: str | None,
    ) -> None:
        prefixes: list[str] = []
        if target_full is not None:
            prefixes.append(target_full)
        if target_subtag is not None:
            for n in range(len(target_subtag), 1, -1):
                prefix = target_subtag[:n]
                if prefix not in prefixes:
                    prefixes.append(prefix)
        if target_pos and target_pos not in prefixes:
            prefixes.append(target_pos)
        for prefix in prefixes:
            for i, wf in enumerate(word.wordforms):
                tag = to_tag(wf)
                if tag == prefix:
                    if i != 0:
                        word.wordforms = [wf] + [w for w in word.wordforms if w is not wf]
                    return
            for i, wf in enumerate(word.wordforms):
                tag = to_tag(wf)
                if tag and tag.startswith(prefix):
                    if i != 0:
                        word.wordforms = [wf] + [w for w in word.wordforms if w is not wf]
                    return

    def _predict_full_tag(self, pos_char: str, feats: dict) -> str | None:
        """Argmax full tag from POS-specific classifier (deprecated by lattice)."""
        entry = self._per_pos_clf.get(pos_char)
        if entry is None:
            return None
        vec, clf = entry
        X = vec.transform([feats])
        return clf.predict(X)[0]

    def score_full_tag(self, pos_char: str, feats: dict) -> dict[str, float] | None:
        """Return `{tag: log_prob}` for every class in the POS-specific classifier.

        This enables lattice rescoring — the analyzer's candidate wordforms
        are scored against this distribution to pick the highest-likelihood
        reading that's actually in the candidate set.
        """
        entry = self._per_pos_clf.get(pos_char)
        if entry is None:
            return None
        vec, clf = entry
        X = vec.transform([feats])
        # `predict_log_proba` is more numerically stable than `predict_proba`
        # and avoids underflow when scoring many tags.
        log_probs = clf.predict_log_proba(X)[0]
        return dict(zip(clf.classes_, log_probs, strict=True))

def _token_features(words: list[str], i: int) -> dict[str, object]:
    """Produces the same feature dict the trainer used. Must stay in sync with
    `tools/train_crf_tagger.py:token_features`."""
    word = words[i]
    lower = word.lower()
    feats: dict[str, object] = {
        "bias": 1.0,
        "word.lower": lower,
        "word.shape": _word_shape(word),
        "word.isupper": word.isupper(),
        "word.istitle": word.istitle(),
        "word.isdigit": word.isdigit(),
        "word.hasdigit": any(c.isdigit() for c in word),
    }
    for n in range(1, 5):
        if len(word) >= n:
            feats[f"suffix-{n}"] = lower[-n:]
            feats[f"prefix-{n}"] = lower[:n]
    if i > 0:
        prev = words[i - 1]
        feats["prev.lower"] = prev.lower()
        feats["prev.shape"] = _word_shape(prev)
    else:
        feats["BOS"] = True
    if i < len(words) - 1:
        nxt = words[i + 1]
        feats["next.lower"] = nxt.lower()
        feats["next.shape"] = _word_shape(nxt)
    else:
        feats["EOS"] = True
    return feats
