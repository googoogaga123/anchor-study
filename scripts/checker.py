"""The checker: does an answer stand on what was retrieved?

This is the live check - it runs on every answer before display and decides
the Unsure label (phase 8). It only sees what the setup retrieved, because in
the app that is all there is. (Scoring Hallucinations for the ladder is a
separate, stricter job against the whole Library: grader.py.)

Two parts, cheapest first:

  1. Quotes   every quoted passage must appear, word for word, in the
              evidence it cites (or, failing that, in any retrieved evidence -
              reported as a wrong source). Free: string matching after
              normalising whitespace, case and typographic quotes/dashes.
  2. Support  an LLM call: is each step of the answer supported by the
              retrieved evidence? Skipped when there is nothing to judge (a
              refusal), and failed without a call when an answer was given
              with no evidence at all.

An answer is Unsure when any quote fails or any step is unsupported - or not
judged at all: the checker fails closed.

The answer contract every setup returns (setups.py):
  {"final_answer": str, "not_found": bool,
   "steps": [{"text": str, "quote": str | None, "source": evidence id | None}],
   "retrieved": [{"id", "file", "loc", "text"}]}
"""
import html
import json
import re

from openai_client import ask_json

SUPPORT_PROMPT = """\
You check whether an answer is supported by the evidence it was given. Use
ONLY the evidence below - not your own knowledge, even if the answer is true.

A step is supported if the evidence states it, or it follows by simple
arithmetic or direct reading from what the evidence states. Linking words
("therefore", "so the answer is") are not claims on their own.

EVIDENCE
{evidence}

QUESTION
{question}

ANSWER, step by step ({n} steps - judge EVERY one, including any that are not
about the question; return exactly {n} entries in "steps")
{steps}

FINAL ANSWER
{final}

Reply with JSON only:
{{"steps": [{{"n": 1, "supported": true, "why": "<short reason; name the evidence id>"}}],
  "final_supported": true}}
"""


SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def norm(s):
    # HTML entities: Docling's markdown writes "&" as "&amp;"; a model quoting
    # the plain "&" quotes the same words (Q05 failed on it).
    s = html.unescape(s or "").lower()
    # Superscripts: the Diagram descriptions write them as "2^nd" / "violation^2"
    # (our own markup), other text as "²". A model quoting "2nd" is quoting the
    # same words, so neither form may fail a quote (Q09 did, twice).
    s = s.replace("^", "").translate(SUPERSCRIPTS)
    # Markdown emphasis and code marks: the figure descriptions write labels as
    # **Cookie** or `S_LR`; a model quoting "Cookie" quotes the same words.
    s = re.sub(r"[*`]", "", s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


def check_quotes(result):
    by_id = {e["id"]: norm(e["text"]) for e in result.get("retrieved", [])}
    everything = " \n ".join(by_id.values())
    out = []
    for i, step in enumerate(result.get("steps", []), 1):
        q = norm(step.get("quote"))
        if not q:
            continue
        src = step.get("source")
        if src in by_id and q in by_id[src]:
            status = "ok"
        elif q in everything:
            status = "wrong_source"
        else:
            status = "not_found"
        out.append({"step": i, "status": status, "source": src, "quote": step.get("quote")})
    return out


def _valid_for(n_steps):
    """One verdict per answer step, numbered 1..n. A reply that skips a step is
    retried: the checker once returned 1 verdict for a 2-step answer and the
    unjudged step - an invented sentence - passed as supported."""
    def valid(v):
        return (isinstance(v.get("steps"), list) and isinstance(v.get("final_supported"), bool)
                and all(isinstance(s, dict) and isinstance(s.get("supported"), bool) for s in v["steps"])
                and sorted(s.get("n") for s in v["steps"]) == list(range(1, n_steps + 1)))
    return valid


def check_support(c, question, result, effort="low"):
    steps = result.get("steps", [])
    if result.get("not_found") and not steps:
        return {"skipped": "refusal"}, None
    if not result.get("retrieved"):
        return {"steps": [{"n": i, "supported": False, "why": "nothing was retrieved"}
                          for i in range(1, len(steps) + 1)],
                "final_supported": False}, None
    evidence = "\n\n".join(f"[{e['id']}] ({e['file']}, {e['loc']})\n{e['text']}"
                           for e in result["retrieved"])
    step_text = "\n".join(f"{i}. {s.get('text', '')}" for i, s in enumerate(steps, 1)) or "(no steps)"
    return ask_json(c, SUPPORT_PROMPT.format(evidence=evidence, question=question,
                                             steps=step_text, n=len(steps),
                                             final=result.get("final_answer", "")),
                    effort=effort, valid=_valid_for(len(steps)), strict=False)


def check(c, question, result):
    """Run both parts. Returns the verdict and the LLM usage (None if no call)."""
    quotes = check_quotes(result)
    support, usage = check_support(c, question, result)
    reasons = [f"step {q['step']}: quote {q['status'].replace('_', ' ')}" for q in quotes
               if q["status"] != "ok"]
    if "skipped" not in support:
        judged = {s.get("n"): s for s in support.get("steps", [])}
        for n in range(1, len(result.get("steps", [])) + 1):
            s = judged.get(n)
            if s is None:  # fail closed: a step nobody judged is not supported
                reasons.append(f"step {n}: not judged by the checker")
            elif not s.get("supported"):
                reasons.append(f"step {n}: not supported ({s.get('why', '')})")
        if not support.get("final_supported", True):
            reasons.append("final answer not supported")
    return {
        "quotes_total": len(quotes),
        "quotes_ok": sum(q["status"] == "ok" for q in quotes),
        "quotes": quotes,
        "support": support,
        "unsure": bool(reasons),
        "unsure_reasons": reasons,
    }, usage


if __name__ == "__main__":
    # Smoke test of the free part: a real quote, a wrong source, an invented one.
    ev = [{"id": "A", "file": "f", "loc": "p. 1", "text": "Use  FileZilla to copy the images folder."},
          {"id": "B", "file": "f", "loc": "p. 2", "text": "Start the server on port 7001."}]
    res = {"retrieved": ev, "steps": [
        {"text": "x", "quote": "use filezilla", "source": "A"},
        {"text": "y", "quote": "port 7001", "source": "A"},
        {"text": "z", "quote": "port 8080", "source": "B"}]}
    print(json.dumps(check_quotes(res), indent=1))
