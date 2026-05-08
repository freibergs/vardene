## What

One or two sentences describing the change.

## Why

The motivation — bug fix, accuracy improvement, new feature, doc clarification, etc. If this addresses an issue, link it (`Fixes #123`).

## Verification

- [ ] `pytest tests/` passes (65/65 expected)
- [ ] `ruff check vardene tests` clean
- [ ] If accuracy-relevant, `python -m tools.benchmark` is within ±0.5 pp of the published numbers (Lemma 96.73 ± 0.29, Tag 92.51 ± 0.29, POS 98.75 ± 0.16)
- [ ] If a new HTTP endpoint, A/B-tested against `http://api.tezaurs.lv:8182/<route>` and any divergence noted below
- [ ] If the paper changed, recompiled cleanly and the regenerated PDF is included

## Divergence from upstream (if any)

Note any intentional difference from the Java reference behaviour and why it's the right call.
