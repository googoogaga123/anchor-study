# 0005 GPT-5.6 Luna, direct from OpenAI, for every model call

Supersedes 0003; returns to 0002's choice.

Every model call - answering, the live checker, the eval grader - uses
`gpt-5.6-luna` through `api.openai.com` with the owner's own OpenAI project
key (17 Oct 2026). Embeddings stay `text-embedding-3-small`.

0003 ran everything on `gpt-5-mini` through the apiyi relay only because the
first key was a relay key and the relay did not offer Luna. That key stopped
working on 17 Oct (401 Invalid token); the new key reaches OpenAI directly and
Luna is on it. Chosen by the owner, with everything model-dependent rerun on
Luna so the Comparison ladder compares like with like.

Consequences:

- Course material goes to OpenAI only, no third-party relay - the privacy
  note in 0003 no longer applies.
- Luna passed the scoring sanity tests exactly as gpt-5-mini did: 0 false
  alarms on the oracle, 21 of 21 planted claims caught by grader and checker.
- The earlier gpt-5-mini runs are kept in `runs/gpt-5-mini/` for history, not
  compared against Luna runs.
- The Diagram descriptions in `parsed/*__png.md` were written by
  gemini-3.5-flash-lite on the relay (0003's exception) and are kept. Gemini is
  not on OpenAI, so the app's vision model is open again: Luna has not been
  tested on the eval images; gpt-5-mini misread the Q07 arrow 7 of 7 times.
