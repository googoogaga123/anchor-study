"""Worked solutions (stretch rung S4): a new problem, solved with the Library's methods.

For questions the router tags `solve` - a problem with new numbers, worked with
a method the course teaches. The Explained answer's rule "answer only what the
excerpts say" can't serve these: the answer is in no excerpt. So:

  0. Evidence  the usual top passages from hybrid search, plus - when the
               Library has spreadsheets - the cells the SQL route's planner
               picks (sheet_cells), since a sheet is never a passage.
  1. Solve     the model writes the steps. Every method, rule or formula is
               quoted word for word from an excerpt; numbers given in the
               question are quoted from the question (source "question").
               It never does arithmetic: each calculation is an expression
               worked out by the calculator (calc.py); the result of step 3 is
               s3, in later calculations and in the text ("profit is {s3}").
  2. Re-solve  a second, independent call solves it again from scratch; the
               numbers in its final answer must be the same as the first's
               (compared as values, so "$15" and "15" agree; names of results
               may differ between the two solves). Code makes the arithmetic
               right; the re-solve guards against a wrong formula or a wrong
               number going in, which code can't see.
  3. Check     the usual checker (quotes and support, the question counting as
               evidence), but not the number check: the re-solve does that job.

The answer says it is a worked solution - a new problem, not quoted from the
materials - and is Unsure if a calculation fails, the re-solve disagrees, or a
check fails. Cost: about 2-3x an Explained answer (two solves, longer replies).
"""
import re

from calc import CalcError, evaluate, same, show
from openai_client import ask_json

EFFORT = "medium"  # a worked solution has more to keep straight; "low" garbled its own references
PROMPT_VERSION = "1"
NOT_FOUND = "Not found in your materials"

PROMPT = """\
A student asks you to work out a problem using the methods in THEIR course
materials. The excerpts below, each with an id, are from those materials. The
problem itself may be new: its numbers come from the question.

Rules:
- Every method, rule, definition or formula you use must come from an excerpt:
  copy the exact words (at most about 25) into "quote" and give that
  excerpt's id in "source". A step that only takes numbers from the question
  quotes words copied exactly from the QUESTION, with "source": "question" -
  never words from an excerpt under "question".
- Give every step an "id": s1, s2, s3 ... in order.
- Never do arithmetic yourself. Put each calculation in "calc" as an
  expression for a calculator. A step's result is called by its id: a later
  calc can use it ("s3 * 2"), and "text" or "final_answer" can show it as
  {s3}, e.g. "so the profit is ${s3}". The calculator fills in the numbers.
  Only refer to ids of steps that have a calc.
  Calculator language: numbers with + - * / ( ), round(x, 2), min(a, b),
  max(a, b), sum([a, b, c]); dates as date(day, month), with days(n) and
  weeks(n). Percentages without %, money without $ or commas. Steps without
  a calculation have "calc": null.
- If the excerpts don't contain a method for this problem, set "not_found" to
  true, give no steps, and set "final_answer" to "Not found in your materials".

EXCERPTS
{excerpts}

QUESTION
{question}

Reply with JSON only:
{{"not_found": false,
  "steps": [{{"id": "s1", "text": "<one step>", "quote": "<exact words>",
             "source": "<excerpt id or question>", "calc": "<expression or null>"}}],
  "final_answer": "<the answer, in one or two sentences, using {{s1}}, {{s2}} ...>"}}"""

NAME = re.compile(r"\{(s\d+)\}")
REF = re.compile(r"\bs\d+\b")
BARE = re.compile(r"-?\d+(?:\.\d+)?")


def _readable(calc, names):
    """A calculation as a student reads it: earlier results by value, x and / for * and /."""
    shown = REF.sub(lambda m: show(names[m.group(0)]) if m.group(0) in names else m.group(0), calc)
    return shown.replace("**", "^").replace("*", "×")


def _valid(v):
    return (isinstance(v.get("not_found"), bool) and isinstance(v.get("final_answer"), str)
            and isinstance(v.get("steps"), list) and all(isinstance(s, dict) for s in v["steps"]))


def _evidence(question, evidence):
    """The excerpts plus the question itself, which a step may quote for the problem's numbers."""
    return list(evidence) + [{"id": "question", "file": "Your question", "loc": "", "text": question}]


def _solve(c, question, evidence):
    """One solve: (worked result, errors, usage). Results are filled in by the calculator."""
    excerpts = "\n\n".join(f"[{e['id']}] ({e['file']}, {e.get('loc') or ''})\n{e['text']}" for e in evidence)
    reply, usage = ask_json(c, PROMPT.replace("{excerpts}", excerpts).replace("{question}", question),
                            effort=EFFORT, valid=_valid)
    names, errors, steps = {}, [], []
    for i, s in enumerate(reply["steps"], 1):
        step = {"text": str(s.get("text") or ""), "quote": s.get("quote") or None, "source": s.get("source") or None}
        calc = s.get("calc")
        if isinstance(calc, str) and calc.strip() and calc.strip().lower() != "null":
            name = str(s.get("id") or f"s{i}").strip()
            name = name if re.fullmatch(r"s\d+", name) else f"s{i}"
            try:
                names[name] = evaluate(calc, names)
                if not BARE.fullmatch(calc.strip()):  # "4" alone is a number, not a calculation worth showing
                    step |= {"calc": _readable(calc.strip(), names), "value": show(names[name])}
            except CalcError as e:
                errors.append(f"step {i}: the calculation couldn't be run ({e})")
                step |= {"calc": calc.strip(), "value": None}
        steps.append(step)

    def fill(text):
        return NAME.sub(lambda m: show(names[m.group(1)]) if m.group(1) in names else m.group(0), text)

    for step in steps:
        step["text"] = fill(step["text"])
    final = fill(reply["final_answer"])
    if NAME.search(final) or any(NAME.search(st["text"]) for st in steps):
        errors.append("a result the answer refers to was never worked out")
    return {"not_found": reply["not_found"], "final_answer": final, "steps": steps}, errors, usage


def sheet_cells(c, question, db=None, spreadsheet=None, cell=None):
    """The spreadsheet cells a problem needs, as evidence (the SQL route's planner picks
    them), so a worked solution can start from the sheet's figures. ([], usages)."""
    import library as L
    import sql_route
    kwargs = {"db": db} if db else {}
    rows, _, usages = sql_route.plan_and_run(c, question, spreadsheet=spreadsheet, **kwargs)
    found, seen = [], set()
    for r in rows or []:
        ref = r.get("cell_ref")
        if ref and ref not in seen and (ev := (cell or L.sheet_cell)(ref)):
            seen.add(ref)
            found.append(ev)
    return found, usages


def _merge(*usages):
    from checker import _merge as merge
    return merge(*usages)


def solve(c, question, evidence):
    """A worked solution with its re-solve, in the answer contract checker.py and the website use."""
    from concurrent.futures import ThreadPoolExecutor
    ev = _evidence(question, evidence)
    with ThreadPoolExecutor(2) as pool:  # the solve and its re-solve are independent: run them side by side
        one, two = pool.submit(_solve, c, question, ev), pool.submit(_solve, c, question, ev)
        (first, errors, u1), (again, errors2, u2) = one.result(), two.result()
    result = {"final_answer": first["final_answer"], "not_found": first["not_found"], "steps": first["steps"],
              "retrieved": ev, "kind": "worked", "model": None, "effort": EFFORT, "prompt_version": PROMPT_VERSION}
    if first["not_found"]:
        result |= {"final_answer": NOT_FOUND, "usage": _merge(u1, u2), "worked_checks": [], "resolve": None}
        return result
    checks = list(errors)
    if again["not_found"]:
        checks.append("an independent re-solve couldn't confirm the answer")
    elif _numbers(first["final_answer"]) != _numbers(again["final_answer"]):
        checks.append(f"an independent re-solve got a different answer: \"{again['final_answer']}\"")
    result["usage"] = _merge(u1, u2)
    result["worked_checks"] = checks
    result["resolve"] = {"final_answer": again["final_answer"], "errors": errors2}
    return result


def _numbers(text):
    """The numbers and dates in an answer, as values: {"$15", "15.0"} -> {15.0}."""
    from number_check import mask
    out = set()
    for token in mask(text)[1]:
        if "/" in token:
            out.add(token.split("/")[0] + "/" + token.split("/")[1])
        else:
            try:
                out.add(round(float(token.replace("$", "").replace(",", "").replace("%", "")), 4))
            except ValueError:
                out.add(token)
    return out
