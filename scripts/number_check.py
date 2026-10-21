"""The number check (stretch rung S4, on every answer): are the final answer's numbers right?

The quote check confirms a step's words are in the files; it cannot see a
number the model worked out itself - a date two weeks on, a total, a capped
mark. Seen live (18 Oct 2026): "Quiz 1 closes 31/8" when the rule ("ends 2
weeks later on Sunday") and the start (Monday 17/8) give Sunday 30/8.

  1. Mask    code takes every number and date out of the final answer
             ("closes on [?1]"), so the next step cannot simply agree with it.
  2. Rework  one model call works each out again from the same excerpts and
             the question, writing a calculation - never a result - in the
             calculator language (calc.py).
  3. Compare the calculator works it out; a value that differs from what the
             answer says makes the answer Unsure, naming both.
  0. Weekday (free, no model call) "Sunday 31/8" in an answer is checked
             against the calendar: 31/8/2026 is a Monday.

Measured 21 Oct 2026 on the 12 saved Build answers that have numbers (all
graded correct) and 4 rebuilt quiz-closing answers, two runs per setting:
  - one reworking, low or medium effort: 0 false alarms in 48 checks; a
    wrong "14/9" caught every time; the original mistake "Sunday 31/8"
    caught in 1 of 4 (the model itself reads "2 weeks later on Sunday" as
    31/8) - which is why the free weekday check is there: it always catches it.
  - an earlier version wrongly flagged Q18 ($6,500 stated outright in the
    excerpt, reworked from scratch), hence "copy a value an excerpt states";
  - a tie-breaking second reworking was tried and dropped: it once cleared a
    wrong answer by repeating its mistake.
The year for weekdays is calc.YEAR (the current year).

A value the model can't work out (null, or a calculation the calculator
refuses) is left alone: this check only ever adds a doubt it can show. Times
(23:59) and numbers inside names (IS114, G7, Q12) are not taken out.
No call at all when the final answer has no numbers or is "not found".
"""
import re

from calc import CalcError, evaluate, same, show
from openai_client import ask_json

MAX_VALUES = 20
TOKEN = re.compile(r"(?<![\w/:.$,])(?:\d{1,2}/\d{1,2}(?:/\d{2,4})?|\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?)(?![\w/:]|[.,]\d)")
TIME = re.compile(r"\b\d{1,2}:\d{2}\b")

PROMPT = """\
A study assistant answered a student's question from excerpts of the student's
course materials. Some numbers and dates were taken out of its final answer and
replaced with [?1], [?2], ... Work out what each one should be yourself, from
the excerpts and the question. Do not guess what the assistant wrote.

Write each one as a calculation for a calculator, which does the arithmetic:
  numbers with + - * / ( ), round(x, 2), min(a, b), max(a, b), sum([a, b, c])
  dates: date(day, month) is a calendar date - a date copied from an excerpt
  is date(day, month) too; days(n) and weeks(n) are lengths of time;
  date(3, 4) + days(10) is ten days after 3 April
A number copied straight from an excerpt or the question is just that number.
If an excerpt already states the value (for example as the result of its own
worked calculation), copy that stated value; do not redo the excerpt's working.
Write a percentage without the % sign (10% is 10), and money without $ or
commas. If the excerpts and the question don't give enough to work one out,
use null.

QUESTION
{question}

EXCERPTS
{excerpts}

FINAL ANSWER, WITH NUMBERS TAKEN OUT
{masked}

Reply with JSON only: {{"values": {{"?1": "<calculation or null>", "?2": "..."}}}}
"""


def mask(text):
    """(masked text, [values as written]) - numbers inside times stay put."""
    times = [(m.start(), m.end()) for m in TIME.finditer(text)]
    found, out, last = [], [], 0
    for m in TOKEN.finditer(text):
        if any(a <= m.start() < b for a, b in times) or len(found) >= MAX_VALUES:
            continue
        found.append(m.group(0))
        out.append(text[last:m.start()] + f"[?{len(found)}]")
        last = m.end()
    out.append(text[last:])
    return "".join(out), found


_DATE = re.compile(r"^\d{1,2}/\d{1,2}")


def _rework(c, prompt, n, effort):
    """One independent reworking: {index: value} for the values it could work out, and its usage."""
    reply, usage = ask_json(c, prompt, effort=effort, valid=lambda v: isinstance(v.get("values"), dict), strict=False)
    out = {}
    for i in range(1, n + 1):
        expr = (reply.get("values") or {}).get(f"?{i}")
        if not isinstance(expr, str) or not expr.strip() or expr.strip().lower() == "null":
            continue
        try:
            value = evaluate(expr)
        except CalcError:
            continue
        if not isinstance(value, (list, str)):
            out[i] = (value, expr.strip())
    return out, usage


def _comparable(stated, value):
    """A written date is only compared with a computed date, and a number with a number."""
    import datetime as dt
    return isinstance(value, dt.date) == bool(_DATE.match(stated.strip()))


WEEKDAY = re.compile(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")


def check_weekdays(text):
    """Free: "Sunday 31/8" must be a Sunday (in calc.YEAR unless the year is given)."""
    import datetime as dt
    from calc import YEAR
    reasons = []
    for m in WEEKDAY.finditer(text or ""):
        year = int(m.group(4)) if m.group(4) else YEAR
        year = year + 2000 if year < 100 else year
        try:
            real = dt.date(year, int(m.group(3)), int(m.group(2))).strftime("%A")
        except ValueError:
            continue
        if real != m.group(1):
            reasons.append(f"a date didn't check out: the answer says {m.group(0)}, but "
                           f"{m.group(2)}/{m.group(3)}/{year} is a {real}")
    return reasons


def check_numbers(c, question, result, effort="medium"):
    """(list of Unsure reasons, usage or None)."""
    final = result.get("final_answer") or ""
    if result.get("not_found") or not result.get("retrieved"):
        return [], None
    reasons = check_weekdays(final)
    masked, values = mask(final)
    if not values:
        return reasons, None
    excerpts = "\n\n".join(f"[{e['id']}] ({e['file']}, {e.get('loc') or ''})\n{e['text']}" for e in result["retrieved"])
    prompt = PROMPT.replace("{question}", question).replace("{excerpts}", excerpts).replace("{masked}", masked)
    reworked, usage = _rework(c, prompt, len(values), effort)
    for i, (value, expr) in sorted(reworked.items()):
        stated = values[i - 1]
        if _comparable(stated, value) and not same(stated, value):
            reasons.append(f"a number didn't check out: the answer says {stated}; worked out again from your "
                           f"files it is {show(value)} ({expr})")
    return reasons, usage
