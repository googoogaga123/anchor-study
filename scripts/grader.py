"""The eval grader: is the answer correct, and does it contain a Hallucination?

Used only for scoring the Comparison ladder. Two separate judgements:

  correct        does the answer match the eval set's correct_answer (and its
                 notes, e.g. "accept an answer that gives the main rule")?
                 For not_in_docs, correct = the answer says the information is
                 not in the materials - decided without a model call.
  Hallucination  does the answer contain at least one claim NOT backed by the
                 user's course material, even if it is true elsewhere
                 (GLOSSARY.md)? Judged against the WHOLE Library
                 (library.library_text, ~17.8k tokens), not what a setup
                 retrieved - so every rung, including "LLM alone", is
                 measured the same way. Owner's decision, 17 Oct 2026.

Shortcuts that need no model call: a refusal with no steps makes no claims,
so it cannot contain a Hallucination.

Until phase 7 validates this grader against the owner's own labels,
Hallucination counts are provisional.
"""
import re

from openai_client import ask_json

GRADER_PROMPT = """\
You grade one answer from a study assistant. The student's course material
(their Library) is given in full below. You decide two separate things.

1. CORRECT - does the answer give the reference answer? Match meaning, not
   wording: "$14,000" and "14000" agree; extra correct detail is fine. Follow
   the grading notes if any. An answer that says the information is not in
   the materials is not correct here (the question has an answer).

2. CLAIMS - list every factual claim the answer makes (in the steps or the
   final answer). For each, decide "backed": true only if the Library states
   it, or it follows by simple arithmetic or direct reading from what the
   Library states. A claim that is true in the real world but NOT in the
   Library is NOT backed. Linking words ("so", "therefore") and statements
   about what the materials do or do not contain are not claims about the
   subject - leave them out unless they are false about the Library.

QUESTION
{question}

REFERENCE ANSWER
{gold}

GRADING NOTES
{notes}

ANSWER TO GRADE
Steps:
{steps}
Final answer: {final}

THE LIBRARY
{library}

Reply with JSON only:
{{"correct": true, "correct_why": "<one sentence>",
  "claims": [{{"claim": "<short>", "backed": true, "where": "<file and place in the Library, or why not backed>"}}]}}
"""

# Ways an answer says "not in your materials". Widened 17 Oct 2026 after an
# answer said "The location is not specified in the provided materials" and was
# not recognised as a refusal. Applies to every setup alike.
NOT_FOUND = re.compile(
    r"not (be )?found in (your|the|these) (provided )?(course )?materials?"
    r"|(isn't|is not|aren't|are not|not) (in|included in|covered in|stated in|mentioned in|given in"
    r"|specified in|provided in) (your|the|these) (provided )?(course )?materials?"
    r"|(your|the|these) (provided )?(course )?materials? (do not|does not|don't|doesn't) "
    r"(say|state|specify|mention|give|include|contain)"
    r"|\bnot (specified|stated)\b", re.I)


def _valid(v):
    return (isinstance(v.get("correct"), bool) and isinstance(v.get("claims"), list)
            and all(isinstance(cl, dict) and isinstance(cl.get("backed"), bool) for cl in v["claims"]))


def says_not_found(result):
    # Curly apostrophes ("don’t") are the same words as straight ones.
    answer = (result.get("final_answer") or "").replace("\u2019", "'").replace("\u2018", "'")
    return bool(result.get("not_found")) or bool(NOT_FOUND.search(answer))


def grade(c, row, result, library, effort="low"):
    """Return (verdict, usage). usage is None when no model call was needed."""
    refused = says_not_found(result)
    steps = result.get("steps", [])
    if row["tag"] == "not_in_docs" and refused and not steps:
        return {"correct": True, "correct_why": "refused, as expected", "claims": [],
                "hallucination": False}, None
    if refused and not steps:
        return {"correct": False, "correct_why": "refused, but the answer is in the Library",
                "claims": [], "hallucination": False}, None

    step_text = "\n".join(f"{i}. {s.get('text', '')}" for i, s in enumerate(steps, 1)) or "(none)"
    gold = row["correct_answer"] if row["tag"] != "not_in_docs" else \
        "Not found in your materials (the Library does not contain this)."
    verdict, usage = ask_json(c, GRADER_PROMPT.format(
        question=row["question"], gold=gold, notes=row.get("notes") or "(none)",
        steps=step_text, final=result.get("final_answer", ""), library=library),
        effort=effort, valid=_valid)
    if row["tag"] == "not_in_docs":
        # Correctness here is decided by the refusal, not the model.
        verdict["correct"] = refused
        verdict["correct_why"] = "refused" if refused else "answered a question the Library cannot answer"
    verdict["hallucination"] = any(not cl.get("backed", False) for cl in verdict.get("claims", []))
    return verdict, usage
