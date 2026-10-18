"""Phase 8: the router - one cheap model call tags each question.

The tag picks the route (build plan, "How a question gets answered"):

  numeric       a number, amount, count, date-free quantity, or a calculation
                -> the SQL route over the Library's spreadsheets, falling back
                   to hybrid search when the spreadsheets cannot answer it
  lookup        a fact, name, place, rule, step or date stated in the material
  relationship  how two or more things in the material connect
  overview      a summary of a topic, section or file
  solve         work out a problem using methods from the material
                -> hybrid search for all four, until a stretch rung beats it

The router sees only the question, never the Library: it decides what KIND of
answer is wanted, not whether the Library holds it ("What is the passing
mark?" is numeric even though the materials never give one).

Model: Luna, reasoning effort low (record 0005).
"""
from openai_client import ask_json

TAGS = ("lookup", "numeric", "relationship", "overview", "solve")

PROMPT = """\
A student asks a question about their own course materials. Tag the KIND of
answer the question wants - not whether the materials contain it.

- numeric: the answer is a number - an amount, total, count, score, mark,
  percentage, port number, or the result of a calculation.
- lookup: the answer is a fact stated in the materials - a name, place, tool,
  rule, step, option, date or time, yes/no.
- relationship: how two or more things connect, compare or depend on each other.
- overview: a summary of a topic, section or whole file.
- solve: work through a problem (an exercise, a calculation with method)
  using methods from the materials, showing the working.

If a question asks for one number found in the materials, it is numeric even
when finding it needs no arithmetic.

QUESTION
{question}

Reply with JSON only: {{"tag": "<one of: lookup, numeric, relationship, overview, solve>"}}
"""


def route(c, question):
    """(tag, usage)."""
    reply, usage = ask_json(c, PROMPT.format(question=question), effort="low",
                            valid=lambda v: v.get("tag") in TAGS)
    return reply["tag"], usage
