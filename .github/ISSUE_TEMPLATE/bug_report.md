---
name: Bug report
about: Report incorrect output, a crash, or behaviour that diverges from api.tezaurs.lv
title: "[bug] "
labels: bug
---

**What you observed**
A clear description of what went wrong. If output is incorrect, paste both the actual and expected outputs.

**To reproduce**
Minimal Python or curl command that triggers the bug:

```python
from vardene.analyzer import Analyzer
a = Analyzer()
a.enable_guessing = True
print(a.analyze("...").wordforms[0])
```

**Expected behaviour**
What you thought should happen, ideally with a pointer to the matching response from `api.tezaurs.lv:8182` (the upstream Java service vardene mirrors).

**Environment**
- Python version (`python --version`):
- Vārdene version (`pip show vardene` or commit hash):
- OS:

**Tag and lemma divergences**
If this is an accuracy regression, run `python -m tools.benchmark` and paste the per-seed numbers — the headline is `Lemma 96.73 ± 0.29, Tag 92.51 ± 0.29, POS 98.75 ± 0.16`. PRs should not regress these by more than ±0.5 pp.
