"""Read a JSON reply that is still being written, for streamed answers.

The answering model replies with one JSON object (answering.py), written left
to right: {"not_found": ..., "steps": [...], "final_answer": "..."}. While it
streams, the text so far is not valid JSON. parse(prefix) returns what the
prefix already says: every finished value, plus the string being written, cut
where the text stops. A half-written key, number or true/false is left out
until it is whole, so nothing shown is ever a guess at what comes next.

    parse('{"steps": [{"text": "The quiz op')  ->  {"steps": [{"text": "The quiz op"}]}
"""
import json

_CLOSE = {"{": "}", "[": "]"}


def parse(prefix):
    """The object the prefix implies so far, or None before it has begun."""
    stack = []   # [opener, state]; state: object "key" | "colon" | "value" | "comma", array "value" | "comma"
    cut = None   # (end, closers): the latest place the text could stop and still be valid
    i, n = 0, len(prefix)

    def closers():
        return "".join(_CLOSE[s[0]] for s in reversed(stack))

    def after_value():
        if stack:
            stack[-1][1] = "comma"

    while i < n:
        ch = prefix[i]
        if ch in " \t\r\n":
            i += 1
        elif ch in "{[":
            stack.append([ch, "key" if ch == "{" else "value"])
            i += 1
            cut = (i, closers())
        elif ch in "}]":
            if not stack:
                break
            stack.pop()
            after_value()
            i += 1
            cut = (i, closers())
            if not stack:
                break  # the object is complete
        elif ch == ":":
            stack[-1][1] = "value"
            i += 1
        elif ch == ",":
            stack[-1][1] = "key" if stack[-1][0] == "{" else "value"
            i += 1
        elif ch == '"':
            j, escaped = i + 1, False
            while j < n:
                if escaped:
                    escaped = False
                elif prefix[j] == "\\":
                    escaped = True
                elif prefix[j] == '"':
                    break
                j += 1
            is_key = bool(stack) and stack[-1][0] == "{" and stack[-1][1] == "key"
            if j >= n:  # the string is still being written
                if is_key or not stack:
                    break
                body = prefix[i + 1:]
                if escaped:  # a lone backslash at the very end
                    body = body[:-1]
                k = body.rfind("\\u")
                if k != -1 and len(body) - k < 6:  # a half-written \uXXXX
                    body = body[:k]
                try:
                    return json.loads(prefix[:i] + '"' + body + '"' + closers())
                except json.JSONDecodeError:
                    break
            i = j + 1
            if is_key:
                stack[-1][1] = "colon"
            else:
                after_value()
                cut = (i, closers())
        else:  # a number, true, false or null
            j = i
            while j < n and prefix[j] not in ",}] \t\r\n":
                j += 1
            if j >= n:
                break  # still being written
            i = j
            after_value()
            cut = (i, closers())
    if cut is None:
        return None
    end, close = cut
    try:
        return json.loads(prefix[:end] + close)
    except json.JSONDecodeError:
        return None
