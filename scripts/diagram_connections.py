"""Connections in a diagram, read three times and kept by majority vote.

Why: no vision model on the relay reads arrows reliably in one pass. On the
IS114 flowchart one Gemini run sent 1st/2nd violations straight from "Discuss"
to "Prepare notice", skipping "Conduct disciplinary proceedings"; another run
pointed the Council's dashed line the wrong way. But the runs were wrong in
DIFFERENT places, and the box text was right every time. So:

  1. Elements  - one call lists every box/label/menu item with an id and its
                 exact text. Text is what models get right; ids give the
                 three readings a shared vocabulary to vote in.
  2. Arrows    - READINGS separate calls list every arrow as from-id -> to-id,
                 with line style and label. A highlight arrow drawn onto a
                 screenshot is ANNOTATION -> the element at its tip.
  3. Vote      - two elements are "connected" when at least AGREE readings
                 link them; direction is voted separately, and reported as
                 disputed if the readings split. Style and label take the
                 majority. Arrows seen fewer times are kept but marked
                 unconfirmed, so nothing is silently dropped.
  4. Render    - the connections section and the step-by-step walk are
                 written by code from the agreed arrows, so the walk cannot
                 contradict them.

Everything the model said is saved to <stem>__png.edges.json for audit.
"""
import base64
import json
import re
import time
from collections import Counter, defaultdict

READINGS = 3
AGREE = 2

NODES_PROMPT = """\
List every element of this image that an arrow, line or drawn annotation could
start at, end at, or point to: boxes, circles or icons with a label, menu
items, buttons, tabs, headings. Give each the exact text written on or under
it, copied verbatim (keep superscripts as e.g. "school^1"). Do NOT list text
that is only a label printed beside a line (a condition such as "minor"), and
do not list footnotes.

Reply with JSON only, no prose:
{"nodes": [{"id": "N1", "text": "<exact text>", "where": "<position, e.g. top-left>"}]}
"""

EDGES_PROMPT = """\
Here are the elements of this image, with ids:

{nodes}

List every arrow or connecting line in the image, using these ids.

- "from" is the tail, "to" is the head - the end with the arrowhead.
- Fill in "tip" FIRST: say in words exactly what is at or just beyond the
  point of the arrowhead (which word or shape it touches or aims at). Then
  choose "to" to match what you wrote in "tip", not the element the arrow's
  body passes over or happens to be near.
- If a line splits or merges, list each branch as its own entry from the
  element the flow comes from to the element it reaches.
- If a line has no visible arrowhead, give the direction the flow reads and
  set "arrowhead" to false.
- A highlight arrow or circle drawn ON TOP of a screenshot is not a connector:
  give it "from": "ANNOTATION" and "to": the element at its tip.
- "style" is "solid" or "dashed". "label" is any text printed on or beside the
  line ("" if none), copied verbatim.
- If the image has no arrows or lines, return an empty list.

Reply with JSON only, no prose:
{{"edges": [{{"from": "N1", "tip": "<what the arrowhead's point touches>", "to": "N2", "style": "solid", "label": "", "arrowhead": true}}]}}
"""


def ask(c, model, path, prompt):
    """One vision call; returns (text, usage)."""
    b64 = base64.b64encode(path.read_bytes()).decode()
    extra = {"reasoning_effort": "medium"} if model.startswith("gpt-5") else {}
    t0 = time.time()
    resp = c.chat.completions.create(model=model, **extra, messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
        ],
    }])
    u = resp.usage
    return resp.choices[0].message.content or "", {
        "model": resp.model, "prompt_tokens": u.prompt_tokens,
        "completion_tokens": u.completion_tokens, "seconds": round(time.time() - t0, 1)}


def parse_json(text):
    """The JSON object in a reply, tolerating ```json fences and stray prose."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    return json.loads(m.group(0))


def vote(readings, node_ids):
    """Vote on which elements are connected, then on which way.

    Connection and direction are voted separately. Two readings that link the
    same pair but point opposite ways agree the pair is connected and disagree
    on direction - so the connection is kept and its direction is reported as
    disputed, rather than letting a 2-1 split pick a direction. (On the IS114
    flowchart the long dashed line has no arrowhead; readings split on it.)
    """
    pairs = defaultdict(list)  # unordered pair -> [(from, to, edge)] one per reading
    for r in readings:
        # Count each pair once per reading, even if listed twice.
        for key, e in {frozenset((e.get("from"), e.get("to"))): e for e in r}.items():
            frm, to = e.get("from"), e.get("to")
            if to in node_ids and (frm in node_ids or frm == "ANNOTATION") and frm != to:
                pairs[key].append((frm, to, e))
    agreed, unconfirmed = [], []
    for found in pairs.values():
        directions = Counter((frm, to) for frm, to, _ in found)
        (frm, to), n_dir = directions.most_common(1)[0]
        es = [e for *_, e in found]
        edge = {
            "from": frm, "to": to, "votes": len(found),
            "direction_disputed": len(directions) > 1,
            "style": Counter(e.get("style", "solid") for e in es).most_common(1)[0][0],
            "label": Counter(" ".join((e.get("label") or "").split()) for e in es).most_common(1)[0][0],
            "tips": [e.get("tip", "") for e in es],
        }
        (agreed if len(found) >= AGREE else unconfirmed).append(edge)
    return agreed, unconfirmed


def walk(nodes, edges):
    """Numbered steps following the agreed arrows from each starting element."""
    text = {n["id"]: n["text"] for n in nodes}
    out_edges = defaultdict(list)
    has_in = set()
    for e in edges:
        if e["from"] != "ANNOTATION" and not e.get("direction_disputed"):
            out_edges[e["from"]].append(e)
            has_in.add(e["to"])
    starts = [n["id"] for n in nodes if n["id"] in out_edges and n["id"] not in has_in]
    lines, visited = [], set()

    def visit(nid, depth):
        pad = "   " * depth
        if nid in visited:
            lines.append(f"{pad}- (joins \"{text[nid]}\", described above)")
            return
        visited.add(nid)
        lines.append(f"{pad}- \"{text[nid]}\"")
        nxt = out_edges.get(nid, [])
        if not nxt:
            lines.append(f"{pad}  - (end of this path)")
        for e in nxt:
            cond = f"if \"{e['label']}\" " if e["label"] else ""
            if len(nxt) > 1 or cond:
                lines.append(f"{pad}  - {cond}({e['style']} line) ->")
                visit(e["to"], depth + 1)
            else:
                visit(e["to"], depth)

    for s in starts:
        visit(s, 0)
    return lines


def render(nodes, agreed, unconfirmed):
    """Markdown for the connections section and the walk."""
    text = {n["id"]: n["text"] for n in nodes}
    lines = [f"## Connections (each confirmed by at least {AGREE} of {READINGS} independent readings)", ""]

    def fmt(e):
        label = f', labelled "{e["label"]}"' if e["label"] else ""
        if e["from"] == "ANNOTATION":
            return f'- A drawn annotation arrow points at "{text[e["to"]]}" ({e["votes"]} of {READINGS} readings)'
        if e.get("direction_disputed"):
            return (f'- "{text[e["from"]]}" and "{text[e["to"]]}" are connected ({e["style"]} line{label}); '
                    f'which way it runs is unclear - the readings disagree')
        return f'- "{text[e["from"]]}" -> "{text[e["to"]]}" ({e["style"]} line{label})'

    lines += [fmt(e) for e in agreed] or ["- (none)"]
    if unconfirmed:
        lines += ["", f"## Unconfirmed connections (seen in fewer than {AGREE} of {READINGS} readings - may be wrong)", ""]
        lines += [fmt(e) + f" [{e['votes']} of {READINGS}]" for e in unconfirmed]
    steps = walk(nodes, agreed)
    if steps:
        lines += ["", "## How to read it (following the confirmed connections)", ""] + steps
    return "\n".join(lines)


def keep_sections(description, names=("What it is", "All text, verbatim")):
    """The named '## ' sections of a free-text description, in order."""
    # Models sometimes mark the image's line breaks as <br>; they are noise in search.
    description = re.sub(r"\s*<br\s*/?>\s*", " ", description)
    parts = re.split(r"(?m)^## ", description)
    kept = [p for p in parts[1:] if any(p.startswith(n) for n in names)]
    return "\n".join("## " + p.rstrip() + "\n" for p in kept)


# For pictures that may be charts (describe_pdf_figures.py). Without it, on the
# midterm graphs the readings reported plotted lines and dotted guides as
# "connections" ("Marginal Benefit" -> "Quantity", labelled "Tea") - 13 of them
# on a graph with no arrow drawn at all.
CHART_NOTE = """
If this picture is a chart or graph: its plotted lines and curves, its axes and
its dotted guide lines are data, not connections - leave them out. List only
arrows drawn on top of the chart (for example one showing a shift, or one
pointing from a label to a line). If there are none, reply {"edges": []}.
"""


def connections(c, model, path, note=""):
    """Run the elements call and READINGS arrow calls; return (markdown, audit, usages).
    `note` is appended to the arrow prompt (CHART_NOTE for pictures inside PDFs)."""
    usages = []
    raw, u = ask(c, model, path, NODES_PROMPT)
    usages.append(u)
    nodes = parse_json(raw)["nodes"]
    for n in nodes:
        n["text"] = " ".join(str(n.get("text", "")).split())
    node_list = "\n".join(f'{n["id"]}: "{n["text"]}" ({n.get("where", "")})' for n in nodes)
    readings = []
    for _ in range(READINGS):
        raw, u = ask(c, model, path, EDGES_PROMPT.format(nodes=node_list) + note)
        usages.append(u)
        try:
            readings.append(parse_json(raw).get("edges", []))
        except (ValueError, json.JSONDecodeError):
            readings.append([])  # an unparseable reading votes for nothing
    agreed, unconfirmed = vote(readings, {n["id"] for n in nodes})
    audit = {"nodes": nodes, "readings": readings, "agreed": agreed, "unconfirmed": unconfirmed}
    return render(nodes, agreed, unconfirmed), audit, usages
