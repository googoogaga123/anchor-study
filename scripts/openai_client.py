"""One place that reads the API key and builds the client.

Calls go straight to OpenAI with gpt-5.6-luna (docs/adr/0005). History: the
first key was for apiyi, an OpenAI-compatible relay without Luna, so record
0003 ran everything on gpt-5-mini there; the Diagram descriptions in parsed/
were written by gemini-3.5-flash-lite on that relay and are kept as they are.

The key lives in .env (gitignored). Both shapes are accepted:

  OPENAI_API_KEY=sk-...
  sk-...                 (a bare key on its own line)

The key is never printed or logged.
"""
import os
import pathlib

from openai import OpenAI

ROOT = pathlib.Path(__file__).resolve().parent.parent

BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
# Every model call: answering, checking, grading (docs/adr/0005).
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")
EMBEDDING_MODEL = "text-embedding-3-small"
# Diagram descriptions. Gemini (record 0003) is not on OpenAI; Luna has not been
# tested on the eval images yet - gpt-5-mini misread the Q07 arrow 7 of 7 times.
# Test before regenerating parsed/*__png.md.
VISION_MODEL = os.environ.get("VISION_MODEL", MODEL)


def load_key():
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    env = ROOT / ".env"
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, _, value = line.partition("=")
            if name.strip().removeprefix("export ").strip() == "OPENAI_API_KEY":
                return value.strip().strip("'\"")
        elif line.startswith("sk-"):
            return line
    raise SystemExit("No OpenAI key found in .env or OPENAI_API_KEY")


def client():
    # max_retries 5 (default 2): a dropped connection mid-run otherwise loses the question.
    return OpenAI(api_key=load_key(), base_url=BASE_URL, max_retries=5)


def ask_json(c, prompt, effort="low", model=None, valid=None, strict=True):
    """One text-only call that must reply with a JSON object. Returns (obj, usage).

    gpt-5-mini bills hidden reasoning tokens, so every caller picks `effort`.
    A reply that is not JSON raises ValueError rather than being guessed at.
    `valid(obj)` checks the reply's shape too - JSON mode guarantees valid JSON,
    not the fields a caller needs (a grader once sent claims as bare strings).
    A wrongly shaped reply is retried once like an unparseable one. With
    strict=False, a parseable reply that still fails `valid` after the retry is
    returned anyway, for callers that handle a partial reply safely.
    """
    import json
    import re
    import time
    model = model or MODEL
    extra = {}
    if model.startswith("gpt-"):
        # JSON mode: the API guarantees a parseable object (a free-text reply
        # once broke a scoring run with a missing comma).
        extra["response_format"] = {"type": "json_object"}
    if model.startswith("gpt-5"):
        extra["reasoning_effort"] = effort
    t0 = time.time()
    tokens_in = tokens_out = reasoning = 0
    fallback = None
    for attempt in range(2):
        resp = c.chat.completions.create(model=model, **extra,
                                         messages=[{"role": "user", "content": prompt}])
        u = resp.usage
        details = getattr(u, "completion_tokens_details", None)
        tokens_in += u.prompt_tokens
        tokens_out += u.completion_tokens
        reasoning += getattr(details, "reasoning_tokens", 0) or 0
        text = resp.choices[0].message.content or ""
        m = re.search(r"\{.*\}", text, re.S)
        try:
            obj = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            obj = None
        if obj is not None and fallback is None:
            fallback = obj
        if obj is not None and (valid is None or valid(obj)):
            break
        obj = None
    else:
        if not strict and fallback is not None:
            obj = fallback
        else:
            raise ValueError(f"no valid JSON of the expected shape after 2 attempts: {text[:200]!r}")
    return obj, {
        "model": resp.model, "prompt_tokens": tokens_in, "completion_tokens": tokens_out,
        "reasoning_tokens": reasoning, "attempts": attempt + 1,
        "seconds": round(time.time() - t0, 1)}


def stream_json(c, prompt, on_text, effort="low", model=None, valid=None):
    """ask_json, streamed: on_text(text so far) runs as the reply arrives, so the
    website can show an answer while it is being written. The same model, JSON
    mode and effort as ask_json, so a streamed answer is the same answer the
    eval scores. A reply that is not valid JSON of the right shape is retried
    once through ask_json (not streamed). Returns (obj, usage)."""
    import json
    import re
    import time
    model = model or MODEL
    extra = {}
    if model.startswith("gpt-"):
        extra["response_format"] = {"type": "json_object"}
    if model.startswith("gpt-5"):
        extra["reasoning_effort"] = effort
    t0 = time.time()
    text, u, resp_model = "", None, model
    stream = c.chat.completions.create(model=model, **extra, stream=True, stream_options={"include_usage": True},
                                       messages=[{"role": "user", "content": prompt}])
    first = None
    for event in stream:
        resp_model = event.model or resp_model
        if event.usage:
            u = event.usage
        if event.choices and (delta := event.choices[0].delta.content):
            if first is None:
                first = time.time() - t0
            text += delta
            on_text(text)
    details = getattr(u, "completion_tokens_details", None)
    usage = {"model": resp_model, "prompt_tokens": u.prompt_tokens if u else 0,
             "completion_tokens": u.completion_tokens if u else 0,
             "reasoning_tokens": (getattr(details, "reasoning_tokens", 0) or 0) if u else 0,
             "attempts": 1, "seconds": round(time.time() - t0, 1),
             "first_text_seconds": round(first, 1) if first is not None else None}
    m = re.search(r"\{.*\}", text, re.S)
    try:
        obj = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        obj = None
    if obj is not None and (valid is None or valid(obj)):
        return obj, usage
    obj, retry = ask_json(c, prompt, effort=effort, model=model, valid=valid)
    usage["prompt_tokens"] += retry["prompt_tokens"]
    usage["completion_tokens"] += retry["completion_tokens"]
    usage["reasoning_tokens"] += retry["reasoning_tokens"]
    usage["attempts"] += retry["attempts"]
    usage["seconds"] = round(time.time() - t0, 1)
    return obj, usage
