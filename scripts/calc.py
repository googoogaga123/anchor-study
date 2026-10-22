"""Calculations run as code (stretch rung S4): a small, safe calculator.

The model never does arithmetic in its head. It writes each calculation as an
expression in this calculator's language; this module works it out. Nothing is
ever passed to Python's eval: the expression is parsed into a syntax tree and
only the pieces below are allowed, so model-written text can never run as code.

  numbers      12, 3.5, 1_000          (and names of earlier results: v1, v2 ...)
  operators    +  -  *  /  //  %  **   ( )        unary -
  functions    round(x) round(x, 2)  abs  min  max  sqrt  floor  ceil
               sum([..]) of a list
  dates        date(31, 8)  or  date(31, 8, 2026)  - a day/month (year default YEAR)
               days(13)  weeks(2)      - lengths of time
               date + days(n), date - days(n), date - date (-> days)
               weekday(date) -> "Sunday"

Limits keep a hostile or broken expression cheap: at most MAX_LEN characters,
powers up to 10**6 in size, results within +/- 1e15.

    evaluate("(14 - 7) * 3")                 -> 21
    evaluate("date(31, 8) + days(13)")       -> date(2026, 9, 13)
    show(evaluate("date(31, 8) + days(13)")) -> "Sunday 13/9"
"""
import ast
import datetime as dt
import math
import operator
import re

YEAR = dt.date.today().year  # a date written without a year is this year's (IS114 AY26-T1: 2026)
MAX_LEN = 300
LIMIT = 1e15


class CalcError(ValueError):
    """The expression isn't one this calculator accepts, or can't be worked out."""


def _date(day, month, year=None):
    try:
        return dt.date(int(year or YEAR), int(month), int(day))
    except (TypeError, ValueError) as e:
        raise CalcError(f"not a date: {day}/{month}") from e


FUNCS = {
    "round": lambda x, n=0: round(x, int(n)) if n else round(x),
    "abs": abs, "min": min, "max": max, "sum": sum,
    "sqrt": lambda x: math.sqrt(x) if x >= 0 else _fail("square root of a negative number"),
    "floor": math.floor, "ceil": math.ceil,
    "date": _date,
    "days": lambda n: dt.timedelta(days=n),
    "weeks": lambda n: dt.timedelta(weeks=n),
    "weekday": lambda d: d.strftime("%A") if isinstance(d, dt.date) else _fail("weekday() needs a date"),
}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def _fail(msg):
    raise CalcError(msg)


def _num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        _fail("expected a number")
    if abs(x) > LIMIT or (isinstance(x, float) and not math.isfinite(x)):
        _fail("number out of range")
    return x


def evaluate(expr, names=None):
    """The value of one expression; `names` maps earlier results (v1, v2 ...) to values."""
    names = names or {}
    expr = (expr or "").strip().replace("×", "*").replace("÷", "/").replace("−", "-")
    if not expr or len(expr) > MAX_LEN:
        _fail("empty or too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CalcError(f"can't read: {expr}") from e

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return _num(node.value)
        if isinstance(node, ast.Name):
            if node.id in names:
                return names[node.id]
            _fail(f"unknown name: {node.id}")
        if isinstance(node, (ast.List, ast.Tuple)):
            if len(node.elts) > 100:
                _fail("list too long")
            return [ev(e) for e in node.elts]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = _num(ev(node.operand))
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            a, b = ev(node.left), ev(node.right)
            if isinstance(a, list) or isinstance(b, list):
                # Lists exist only as arguments to sum()/min()/max(). Allowing
                # list * int or list + list lets "[0]*10**9" build a huge list
                # and exhaust memory (the power guard doesn't see it).
                _fail("a list can only go inside sum(), min() or max()")
            if isinstance(node.op, ast.Pow):
                if abs(_num(b)) > 100 or abs(_num(a)) > 10 ** 6:
                    _fail("power too large")
            dates = isinstance(a, (dt.date, dt.timedelta)) or isinstance(b, (dt.date, dt.timedelta))
            if dates and not isinstance(node.op, (ast.Add, ast.Sub)):
                _fail("dates can only be added to or subtracted from")
            try:
                v = OPS[type(node.op)](a, b)
            except ZeroDivisionError as e:
                raise CalcError("division by zero") from e
            except (TypeError, OverflowError) as e:
                raise CalcError(f"can't combine these: {expr}") from e
            if isinstance(v, dt.timedelta) and isinstance(a, dt.date) and isinstance(b, dt.date):
                return v.days  # date - date: a number of days
            return v if isinstance(v, (dt.date, dt.timedelta, list)) else _num(v)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and not node.keywords:
            if len(node.args) > 3:
                _fail("too many arguments")
            try:
                v = FUNCS[node.func.id](*[ev(a) for a in node.args])
            except CalcError:
                raise
            except (TypeError, ValueError) as e:
                raise CalcError(f"can't work out {node.func.id}(...)") from e
            return v if isinstance(v, (dt.date, dt.timedelta, str)) else _num(v)
        _fail(f"not allowed in a calculation: {type(node).__name__}")

    return ev(tree)


def show(value):
    """A value as a student would write it: 21, 3.5, "Sunday 13/9"."""
    if isinstance(value, dt.date):
        return f"{value.strftime('%A')} {value.day}/{value.month}"
    if isinstance(value, dt.timedelta):
        return f"{value.days} days"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_NUM = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?%?")


def same(stated, value, rel=0.005):
    """Does a value as written in an answer ("$22,000", "10%", "13/9", "Sunday 13/9") match a computed one?"""
    stated = (stated or "").strip()
    if isinstance(value, dt.date):
        m = _DATE.search(stated)
        return bool(m) and (int(m.group(1)), int(m.group(2))) == (value.day, value.month)
    if isinstance(value, str):
        return value.lower() in stated.lower()
    m = _NUM.search(stated.replace(" ", ""))
    if not m or not isinstance(value, (int, float)):
        return False
    try:
        x = float(m.group(0).replace("$", "").replace(",", "").replace("%", ""))
    except ValueError:
        return False
    return abs(x - value) <= max(rel * abs(value), 0.005)
