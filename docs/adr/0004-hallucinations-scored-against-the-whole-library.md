# 0004 Hallucinations are scored against the whole Library

For the Comparison ladder, a Hallucination is judged by a grader that reads
the entire eval Library (all 7 files, ~17.8k tokens including the
spreadsheet), not just what a setup retrieved. The live checker - which
decides the Unsure label in the app - still judges against retrieved text, and
its verdict is recorded beside the score.

The glossary defines a Hallucination as a claim not backed by the user's
course material. Judging against retrieved text instead would make rung 1
(LLM alone, which retrieves nothing) count every answer as a Hallucination by
construction - even "FileZilla", which is correct and in the files - so rung 1
would be worst by definition rather than by measurement, and the ladder could
not show how much retrieval actually cuts the rate.

Chosen by the owner, 17 Oct 2026. Cost: one grader call of ~19k input tokens
per answered question. The whole-Library approach only works while a Library
fits in one prompt; the eval Library does, real users' Libraries need not, so
this is a scoring method, never the app's checker.

Phase 7 validates this grader against the owner's own labels; until then,
Hallucination counts are provisional.
