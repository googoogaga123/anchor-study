"""The `solve` questions for stretch rung S4 (worked solutions): eval_set_solve.csv.

A solve question is a NEW problem worked with a method the Library teaches -
not one of its own exercises (those are lookups: the answer is printed there).
So every question here is a variation of a worked example in the Library with
new numbers, and every correct answer is computed by the code below, never
typed by hand (build plan: "variations computed in code, 1 in 5 hand-checked";
the owner checks all 10 before any is scored).

  monopoly   midterm Q11: one uniform price, a WTP table, constant marginal
             cost -> the profit-maximising quantity, price and profit
  coase      midterm Q12: two people, two events, a shared-experience bonus
             -> the socially efficient outcome and its total WTP
  menu       midterm Q16: a price for one scoop and a price for two, two
             customer types -> the most profitable menu and its profit
  ledger     the accounting worksheet: one figure changed, everything else
             as in the sheet -> the new net or operating profit
  grading    IS114: quiz marks and the weekly participation cap
  dates      IS114: when a week's revision quiz closes

Every variation must have ONE best answer; a tie stops the script.
7 questions go to the Build set and 3 to the locked Test set, chosen at random
with a fixed seed (one per family where possible), before anything is built.

    .venv/bin/python scripts/make_solve_set.py      # writes eval_set_solve.csv
"""
import csv
import datetime as dt
import itertools
import pathlib
import random
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "eval_set_solve.csv"
MIDTERM, SHEET = "MidtermSampleSolutions.pdf", "3A-Adjust-Class-Worksheet (Answer Key) (1).xlsx"
IS114 = "IS114 AY26-T1 Course Content, Student Edition.pdf"
YEAR = 2026  # IS114 AY26-T1: week 1 starts Monday 17/8/2026


def unique_best(options, key):
    best = max(options, key=key)
    if sum(1 for o in options if key(o) == key(best)) > 1:
        sys.exit(f"tie for the best answer: {[o for o in options if key(o) == key(best)]}")
    return best


def monopoly(wtp, mc):
    """Uniform price: selling Q units means pricing at the Q-th highest WTP (midterm Q11)."""
    values = sorted((v for pair in wtp.values() for v in pair), reverse=True)
    q, price = unique_best([(q, values[q - 1]) for q in range(1, len(values) + 1)],
                           key=lambda qp: (qp[1] - mc) * qp[0])
    return q, price, (price - mc) * q


def coase(x, y, bonus):
    """Total WTP of each outcome (midterm Q12): together earns each person the bonus."""
    outcomes = {"both go to the football game": x["football"] + y["football"] + 2 * bonus,
                "both go to the opera": x["opera"] + y["opera"] + 2 * bonus,
                "X goes to the football game and Y to the opera": x["football"] + y["opera"],
                "X goes to the opera and Y to the football game": x["opera"] + y["football"]}
    best = unique_best(list(outcomes.items()), key=lambda kv: kv[1])
    return best


def menu(types, mc, top=40):
    """Best price for one scoop (p1) and for two (p2) (midterm Q16). Each type picks the
    option with the most surplus, buying more when indifferent (as the midterm's answer does);
    two single scoops at 2 x p1 are an option too. Reproduces the midterm's own answer
    (one scoop $8, two $14, profit $6,500)."""
    def profit(p1, p2):
        total = 0
        for n, (w1, w2) in types.values():
            choices = [(0, 0, 0), (w1 - p1, 1, p1), (w1 + w2 - p2, 2, p2), (w1 + w2 - 2 * p1, 2, 2 * p1)]
            surplus, scoops, pay = max(choices, key=lambda c: (c[0], c[1], -c[2]))
            total += n * (pay - mc * scoops)
        return total
    grid = [(p1, p2) for p1, p2 in itertools.product(range(top + 1), repeat=2) if p2 >= p1]
    best = max(profit(*p) for p in grid)
    winners = [p for p in grid if profit(*p) == best]
    if len(winners) > 1:
        sys.exit(f"several best menus: {winners}")
    # The course's method must be what wins: one scoop at the low type's first-scoop WTP, two
    # scoops at that plus the high type's second-scoop WTP. (An earlier variation, $12/$7 and
    # $9/$5, was won by selling two scoops to everyone - a strategy the course never shows.)
    (_, (_, high2)), (_, (low1, _)) = sorted(types.values(), key=lambda t: -t[1][0])
    assert winners == [(low1, low1 + high2)], winners
    return best, winners[0]


def ledger():
    con = duckdb.connect(str(ROOT / "parsed" / "sheets.duckdb"), read_only=True)
    cell = lambda ref: float(con.execute("SELECT value_num FROM cells WHERE cell_ref = ?", [ref]).fetchone()[0])  # noqa: E731
    v = {name: cell(f"Income Statement!{ref}") for name, ref in
         [("revenue", "C4"), ("salaries", "B6"), ("rent", "B7"), ("supplies", "B8"), ("depreciation", "B9"),
          ("utilities", "B10"), ("interest", "B11"), ("expenses", "C12"), ("net_profit", "C13"),
          ("operating_profit", "C32")]}
    con.close()
    assert v["revenue"] - v["expenses"] == v["net_profit"], v
    assert v["revenue"] - (v["expenses"] - v["interest"]) == v["operating_profit"], v
    return v


def money(x):
    return f"${x:,.0f}"


def build():
    q = []
    # monopoly (Q11)
    for i, (wtp, mc) in enumerate([({"A": (15, 10), "B": (12, 6), "C": (8, 4)}, 5),
                                   ({"A": (20, 14), "B": (16, 9), "C": (11, 6)}, 7)], 1):
        qty, price, prof = monopoly(wtp, mc)
        table = "; ".join(f"consumer {k}: ${a} for the first cup and ${b} for the second" for k, (a, b) in wtp.items())
        q.append(("monopoly", f"A monopolist sells cups of coffee to three consumers who each want at most two cups. "
                  f"Their willingness to pay is {table}. The monopolist charges one uniform price for every cup "
                  f"(no discount on a second cup) and its marginal cost is constant at ${mc} per cup. Using the "
                  f"method in my course materials, what are the profit-maximising quantity and price, and the profit?",
                  f"{qty} cups at {money(price)} each; profit {money(prof)}",
                  f"Uniform price = the {qty}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(qty, 'th')} highest WTP (${price}); profit = ({price} - {mc}) x {qty} = {prof}. "
                  "Correct only if quantity, price and profit all match.", "p. 10 (Q11, method)"))
    # coase (Q12)
    x, y, bonus = {"football": 450, "opera": 120}, {"football": 220, "opera": 380}, 100
    outcome, total = coase(x, y, bonus)
    q.append(("coase", f"Two friends, X and Y, must each choose between a football game and an opera on the same night; "
              f"the tickets cost the same. Attending alone, X's willingness to pay is ${x['football']} for the football "
              f"game and ${x['opera']} for the opera; Y's is ${y['football']} for the football game and ${y['opera']} "
              f"for the opera. If they attend the same event, each gets an extra ${bonus} of willingness to pay. "
              "Using the method in my course materials, what is the socially efficient outcome, and what is its total "
              "willingness to pay?", f"{outcome[0].upper() + outcome[1:]}; total WTP {money(total)}",
              "Compare total WTP of every outcome: together adds 2 x the bonus. Correct only if the outcome and the "
              "total both match.", "p. 11 (Q12, method)"))
    # menu (Q16)
    for types, mc in [({"A": (300, (13, 7)), "B": (300, (9, 4))}, 2)]:
        best, (p1, p2) = menu(types, mc)
        desc = " and ".join(f"{n} are Type {k}, who will pay ${w1} for a first scoop and ${w2} for a second"
                            for k, (n, (w1, w2)) in types.items())
        q.append(("menu", f"An ice cream shop has a constant marginal cost of ${mc} per scoop. Each day {sum(n for n, _ in types.values())} "
                  f"customers visit: {desc}. Each buys at most two scoops, and the shop cannot charge different "
                  "types different prices, but it can set one price for a single scoop and another for two scoops. "
                  "A customer who is indifferent between two options buys more scoops. Using the method in my "
                  "course materials, what prices should the shop set, and what is the highest daily profit it can make?",
                  f"One scoop ${p1} and two scoops ${p2}; profit {money(best)} per day",
                  f"Brute force over whole-dollar menus, a customer buys more when indifferent (stated in the question, "
                  f"as in the course's worked answer). The only best menu: one scoop ${p1}, two scoops ${p2} - Type A "
                  f"buys two, Type B one. Correct only if both prices and the profit match.",
                  "p. 20 (Q16, method)"))
    # ledger
    v = ledger()
    q.append(("ledger", "In my accounting worksheet for Eagle Soccer Academy, if December's service revenue had been "
              "$80,000 and every expense had stayed the same, what would the net profit be (pre-IFRS 18 format)?",
              money(80000 - v["expenses"]), f"80,000 - total expenses {v['expenses']:,.0f} (Income Statement!C12).",
              "Income Statement!C4, C12"))
    q.append(("ledger", "In my accounting worksheet for Eagle Soccer Academy, if rent expense for December had been twice "
              "as high and everything else had stayed the same, what would the net profit be (pre-IFRS 18 format)?",
              money(v["net_profit"] - v["rent"]), f"Net profit {v['net_profit']:,.0f} - extra rent {v['rent']:,.0f}.",
              "Income Statement!B7, C13"))
    q.append(("ledger", "In my accounting worksheet for Eagle Soccer Academy, if utilities expense for December had been "
              "$12,000 and everything else had stayed the same, what would the operating profit be under the IFRS 18 "
              "format?", money(v["operating_profit"] - (12000 - v["utilities"])),
              f"Operating profit {v['operating_profit']:,.0f} - extra utilities {12000 - v['utilities']:,.0f}; interest "
              "is not an operating expense under IFRS 18.", "Income Statement!B30, C32"))
    # grading (IS114 p. 3-4)
    q.append(("grading", "In IS114, if I complete 11 revision quizzes, how many percent of my final grade do I earn from "
              "the revision quizzes?", "10%", "1% per completed quiz, capped at 10% for the whole term: min(11, 10).",
              "p. 3 (Assessments table)"))
    q.append(("grading", "In IS114, if in one week I speak up in my lesson, complete the Session Reflection Form "
              "correctly by the end of the lesson, and also finish one other task from the teaching team, how much "
              "participation do I earn that week?", "2%",
              "1% + 1% + other task, but participation is capped at 2% per week.", "pp. 3-4 (Assessments table)"))
    # dates (IS114 p. 1, 3)
    week3 = dt.date(YEAR, 8, 31)
    assert week3.weekday() == 0
    close = week3 + dt.timedelta(days=13)
    q.append(("dates", "In IS114, the revision quiz released in week 3 opens on the Monday that week starts. On what date "
              "and at what time does it close?", f"{close.strftime('%A')} {close.day}/{close.month}, 23:59",
              f"Week 3 starts Monday 31/8; ends 2 weeks later on Sunday 23:59 = 31/8 + 13 days = {close.isoformat()}.",
              "pp. 1, 3 (Schedule; Assessments table)"))
    assert len(q) == 10, len(q)
    return q


def main():
    rows = build()
    rng = random.Random(20261021)
    test = set()
    families = sorted({r[0] for r in rows})
    for fam in rng.sample(families, 3):  # 3 locked Test questions, from 3 different families
        test.add(rng.choice([i for i, r in enumerate(rows) if r[0] == fam]))
    source = {"monopoly": MIDTERM, "coase": MIDTERM, "menu": MIDTERM, "ledger": SHEET, "grading": IS114, "dates": IS114}
    fmt = {MIDTERM: "PDF", SHEET: "Spreadsheet", IS114: "PDF"}
    subject = {MIDTERM: "COR2100", SHEET: "Accounting", IS114: "IS114"}
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "tag", "set", "group", "wording", "question", "correct_answer", "source_file", "file_format",
                    "location", "subject", "verified", "notes"])
        for i, (fam, question, answer, notes, loc) in enumerate(rows):
            src = source[fam]
            w.writerow([f"S{i + 1:02d}", "solve", "Test" if i in test else "Build", "solve", fam, question, answer,
                        src, fmt[src], loc, subject[src], "", notes])
    print(f"{OUT.name}: {len(rows)} questions, {len(rows) - len(test)} Build, {len(test)} Test (locked)")


if __name__ == "__main__":
    main()
