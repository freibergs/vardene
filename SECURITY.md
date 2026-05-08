# Security Policy

## Reporting a Vulnerability

If you discover a security issue in Vārdene, please **do not** open a public GitHub issue. Instead, email the maintainer directly:

**hello@rihards.dev**

Include in your report:
- A description of the vulnerability and its potential impact
- Steps to reproduce (a minimal proof-of-concept is appreciated)
- Affected versions
- Your suggested mitigation, if any

You can expect an acknowledgement within 7 days. If the issue is confirmed, a fix will be released as soon as the patch is ready, and you will be credited in the [CHANGELOG](CHANGELOG.md) (unless you prefer to remain anonymous).

## Scope

The morphology engine and HTTP service are designed for trusted-input use cases (analysis of Latvian text). The Flask demo app at `vardene/api/app.py` is intended for development and on-premises deployment; it is **not hardened** for direct exposure to the public internet without a reverse proxy that enforces request-size limits, rate limits, and authentication.

In particular, the following are known and **out of scope**:

- Denial-of-service via pathological tokenisation input (very long strings, deeply nested punctuation, etc.). The Splitting state machine is `O(n)` in the input size; large inputs will simply be slow.
- Memory exhaustion via unbounded `inflect()` queries that produce thousands of forms. Wrap the API in a request-size limit if exposing publicly.

In scope and treated as security issues:

- Code execution, file-system access, or unsanitised shell-out via any input.
- Any way to read files outside the working directory through the API.
- Bypass of the lemma/inflection result type contracts that could mislead downstream pipelines.

## Supported Versions

Only the latest minor release on `master` is supported with security fixes. As of 2026-05-08, that is **0.1.x**.
