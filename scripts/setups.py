"""Setups the scoring script can run. Each takes (client, row) and returns the
answer contract described in checker.py.

A real setup - a rung of the Comparison ladder - may read only row["question"].
The setups here marked CHEATS read the answer key on purpose: they exist to
test the scoring itself, not to be scored. score.py labels them so.

  refuse          always "Not found in your materials", retrieves nothing.
                  Expect: not_in_docs 7 of 7 refused, all hollow; answerable
                  0 correct; no model calls at all.
  oracle          gives the answer key's answer, retrieving the right file and
                  quoting the passage the parse-ceiling probes found. Expect:
                  every answerable question correct and no Hallucinations - any
                  flagged is a grader false alarm (or an answer-key entry the
                  Library does not back).
  oracle_planted  the oracle plus one invented sentence in every answer.
                  Expect: every question flagged as a Hallucination; a miss
                  means the grader cannot be trusted.

Ladder rungs (real setups, they read only the question):

  llm_alone       rung 1 (phase 4): the model answers from its own knowledge,
                  no documents. It may say it does not know.
  vector_3small   rung 2 (phase 5): the top K chunks by text-embedding-3-small
  vector_bgem3    rung 2 (phase 5): the top K chunks by self-hosted bge-m3
                  K = 5, not the plan's 20: the eval Library is 25 chunks, so
                  20 would hand over 80% of it whatever the ranking (owner's
                  decision, 17 Oct 2026).
  hybrid          rung 3 (phase 6), the baseline: keyword + vector search in
                  Postgres, merged by RRF, reranked by bge-reranker-v2-m3,
                  top K to the model.

The app's own route (phase 8):

  routed          router.py tags the question; numeric -> sql_route.py over
                  the spreadsheets (DuckDB), falling back to hybrid when the
                  spreadsheets cannot answer; every other tag -> hybrid.
"""
import json
import pathlib
import re

import library as L
import embed
import hybrid as H
from answering import ask_no_docs, ask_with_docs
from checker import norm

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROBES = json.loads((ROOT / "scripts" / "probes.json").read_text())
NOT_FOUND = "Not found in your materials"
PLANTED = ("This was confirmed by the course coordinator, Dr. Lim, during the "
           "Week 3 lecture.")


def _key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _evidence_for(row):
    """The right file's chunks, or the cited spreadsheet cell."""
    if row["file_format"] == "Spreadsheet":
        ev = L.sheet_cell(row["location"].strip())
        return [ev] if ev else []
    want = _key(row["source_file"])
    return [L.as_evidence(c) for c in L.chunks() if _key(c["file"]) == want]


def _probe_quote(row, evidence):
    """The first parse-ceiling probe string found in the evidence, with its source."""
    texts = [p for items in PROBES.values() if isinstance(items, list)
             for it in items if it["id"].rstrip("b") == row["id"] for p in it.get("text", [])]
    for t in texts:
        for e in evidence:
            if norm(t) in norm(e["text"]):
                return t, e["id"]
    if row["file_format"] == "Spreadsheet" and evidence:
        return evidence[0]["text"].split(" (")[0], evidence[0]["id"]
    return None, None


def refuse(c, row):
    return {"final_answer": NOT_FOUND, "not_found": True, "steps": [], "retrieved": []}


def oracle(c, row):
    if row["tag"] == "not_in_docs":
        return {"final_answer": NOT_FOUND, "not_found": True, "steps": [],
                "retrieved": [L.as_evidence(ch) for ch in L.chunks()]}
    evidence = _evidence_for(row)
    quote, source = _probe_quote(row, evidence)
    return {"final_answer": row["correct_answer"], "not_found": False,
            "steps": [{"text": row["correct_answer"], "quote": quote, "source": source}],
            "retrieved": evidence}


def oracle_planted(c, row):
    r = oracle(c, row)
    r["steps"] = r["steps"] + [{"text": PLANTED, "quote": None, "source": None}]
    return r


def llm_alone(c, row):
    return ask_no_docs(c, row["question"])


K = 5


def _vector(model):
    def setup(c, row):
        hits = embed.search(model, row["question"], K)
        return ask_with_docs(c, row["question"], [L.as_evidence(ch) for _, ch in hits])
    setup.__name__ = f"vector_{model}"
    setup.CHEATS = False
    return setup


def hybrid(c, row):
    hits = H.search(row["question"], K)
    return ask_with_docs(c, row["question"], [L.as_evidence(ch) for ch in hits])


hybrid.CHEATS = False


def _sum_usage(usages):
    us = [u for u in usages if u]
    if not us:
        return None
    return {"model": us[0].get("model"), "calls": len(us),
            "prompt_tokens": sum(u["prompt_tokens"] for u in us),
            "completion_tokens": sum(u["completion_tokens"] for u in us)}


def routed(c, row, tagged=None):
    """Phase 8: the router tags the question; numeric goes to the SQL route over
    the spreadsheets, falling back to hybrid search; every other tag goes to
    hybrid search (until a stretch rung beats it on that tag).
    `tagged`: (tag, usage) when the router has already run (routed_s4)."""
    import router
    import sql_route
    tag, r_usage = tagged or router.route(c, row["question"])
    route = {"tag": tag, "path": "hybrid"}
    extra = [r_usage]
    result = None
    if tag == "numeric":
        result, trace = sql_route.answer(c, row["question"])
        extra += trace.pop("plan_usage", [])
        route["sql"] = trace
        route["path"] = "sql" if result else "sql -> hybrid"
    if result is None:
        result = hybrid(c, row)
    result["route"] = route
    result["route_usage"] = _sum_usage(extra)
    return result


routed.CHEATS = False


def routed_s4(c, row):
    """Stretch rung S4: routed, except that questions tagged `solve` get a worked
    solution (worked.py: methods quoted, calculations run as code, a re-solve)."""
    import router
    import worked
    tag, r_usage = router.route(c, row["question"])
    if tag != "solve":
        return routed(c, row, tagged=(tag, r_usage))
    evidence = [L.as_evidence(h) for h in H.search(row["question"], K)]
    cells, plan_usage = worked.sheet_cells(c, row["question"])
    result = worked.solve(c, row["question"], evidence + cells)
    result["route"] = {"tag": tag, "path": "solve", "cells": len(cells)}
    result["route_usage"] = _sum_usage([r_usage, *plan_usage])
    return result


routed_s4.CHEATS = False

vector_3small = _vector("3small")
vector_bgem3 = _vector("bgem3")

refuse.CHEATS = False
llm_alone.CHEATS = False
oracle.CHEATS = True
oracle_planted.CHEATS = True

SETUPS = {f.__name__: f for f in (refuse, oracle, oracle_planted, llm_alone,
                                   vector_3small, vector_bgem3, hybrid, routed, routed_s4)}
