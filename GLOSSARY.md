# Glossary

The words this project uses. Terms only — how things are built lives in the
[build plan](https://claude.ai/code/artifact/83b940f2-c2e2-4bbf-9813-42079907941e),
which wins on any conflict. Update this file the moment a term is settled.

- **User:** anyone who signs up publicly and gets their own login and one Library. Every user is either an Admin or a Member. _Avoid:_ team, member (lowercase), client
- **Admin:** one of at most 3 users (incl. the owner) with no question limit and up to 200 pages of uploads while on the Demo budget. Only the owner makes Admins; any Admin can reset a Member's upload. _Avoid:_ superuser, owner
- **Member:** any user who isn't an Admin. One file ever (max 50 pages) and 3 questions in total; an Admin can reset either. _Avoid:_ guest, friend, basic user
- **Library:** one user's own collection of uploaded course material. Only its owner can search it; nothing is shared between Libraries. _Avoid:_ corpus, knowledge base, shared library
- **Course material:** the files for one course a user puts into their Library: slides, notes, readings, textbooks, sheets. Any subject. _Avoid:_ documents, materials, data
- **Sourced answer:** a reply quoted from the user's own Library and checked against it. If nothing is relevant, it says "Not found in your materials" and offers a Web answer. _Avoid:_ grounded answer, verified answer
- **Explained answer:** the default form of every reply: step-by-step reasoning with a citation to the user's files at each step. _Avoid:_ worked answer, detailed answer
- **Worked solution:** step-by-step reasoning for a new problem, citing methods from the Library, with every calculation run as code. Labelled as not quoted from the materials. _Avoid:_ generated answer, solved answer
- **Web answer:** a reply from internet sources, only when the user agrees to search the web, labelled with its links. _Avoid:_ fallback answer, general answer
- **Unsure label:** a tag on any answer whose checks failed, naming which check failed and why. _Avoid:_ low confidence, warning
- **Demo budget:** the one-off spending limit the app runs on ($1 OpenAI; $10 Voyage only if used). When it runs out, the app says so and stops answering. _Avoid:_ monthly cap, quota
- **Testing budget:** a separate one-off $5 used only for eval runs. _Avoid:_ eval cost, dev budget
- **Self-hosted model:** a model running on the app's own server, free per use; never means the owner's laptop. _Avoid:_ local model
- **Hallucination:** an answer with at least one claim not backed by the user's course material, even if true elsewhere. _Avoid:_ wrong answer, error, made-up answer
- **Hallucination rate:** answers with a Hallucination ÷ total answers, reported as a count (e.g. 3 of 21). _Avoid:_ accuracy, error rate
- **Build set:** eval questions used freely while building and tuning: 7 per tag (21 for now). _Avoid:_ training set, dev set
- **Test set:** eval questions locked away, 3 per tag (9 for now), run once at the end. _Avoid:_ holdout, validation set
- **Comparison ladder:** the ordered setups run on the same Build set and scored the same way, each adding one thing. The winner alone runs on the Test set. _Avoid:_ benchmark, baseline run
- **Diagram description:** a text description of one diagram, written once at upload by a vision model, then searched and cited like normal text. Max 20 per Member file. _Avoid:_ image caption, alt text
