#!/usr/bin/env python3
"""Step 3 — THE GATE. Do not generate any report until this passes.

Seven independent checks. If any fails, the ledger is wrong and every downstream
number (total spend, annual fees, interest) would be wrong too. The script exits
with code 2 on failure so an orchestrator cannot accidentally continue.

  V1 period coverage vs downloaded PDFs (missing / duplicated months)
  V2 per-statement reconciliation: prev + charges - payments = current
  V3 sum of transactions = charges - payments, per statement
  V4 cross-period linkage: previous current = this period's prev
  V5 full-period closure: opening + sum(all net transactions) = closing balance
  V6 category totals equal the transaction total
  V7 no non-monetary rows (points/miles) and no unknown currency leaked in

Usage: python3 validate_ledger.py --out ./audit_out
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import D, TOL, dump_csv, f, read_csv, read_json, to_dec, write_json  # noqa: E402

ZERO = Decimal("0")
TOLERANCE = TOL


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= TOLERANCE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./audit_out")
    ap.add_argument("--base-currency", default="人民币")
    ap.add_argument("--allow-missing-periods", action="store_true",
                    help="some issuers skip months with no activity")
    ap.add_argument("--tolerance", default="0.01")
    args = ap.parse_args()
    global TOLERANCE
    TOLERANCE = Decimal(args.tolerance)
    out = Path(args.out).resolve()
    txns = read_csv(out / "transactions.csv")
    stmts = sorted(read_csv(out / "statements.csv"), key=lambda r: r["period"])
    summ = read_csv(out / "summary_all.csv")
    manifest = read_csv(out / "manifest.csv")
    if not txns or not stmts:
        raise SystemExit("Missing transactions.csv / statements.csv — run parse_statements.py first")

    base = [t for t in txns if t["currency"] == args.base_currency]
    foreign = [t for t in txns if t["currency"] != args.base_currency]
    by_period = defaultdict(list)
    for t in base:
        by_period[t["period"]].append(t)
    stmt_periods = [s["period"] for s in stmts]
    pdf_periods = sorted(r["period"] for r in manifest) if manifest else stmt_periods

    checks = []

    def add(cid, name, failures, detail=None, samples=None):
        checks.append({
            "id": cid, "name": name, "passed": len(failures) == 0,
            "failures": len(failures), "detail": detail or "",
            "samples": (samples or [])[:12],
        })

    # V1 coverage
    miss_pdf = sorted(set(pdf_periods) - set(stmt_periods))
    extra = sorted(set(stmt_periods) - set(pdf_periods))
    dup = [p for p, n in Counter(stmt_periods).items() if n > 1]
    p_first, p_last = (pdf_periods[0], pdf_periods[-1]) if pdf_periods else ("", "")
    missing_months = []
    if p_first and p_last:
        y, m = map(int, p_first.split("-"))
        ey, em = map(int, p_last.split("-"))
        while (y, m) <= (ey, em):
            key = "%04d-%02d" % (y, m)
            if key not in set(pdf_periods):
                missing_months.append(key)
            m += 1
            if m == 13:
                y, m = y + 1, 1
    v1_fail = miss_pdf + extra + dup + ([] if args.allow_missing_periods else missing_months)
    add("V1", "Period coverage (no gaps, no duplicates)",
        v1_fail,
        "%d PDFs / %d statements / %s -> %s / %d missing months"
        % (len(pdf_periods), len(stmts), p_first, p_last, len(missing_months)),
        [{"period": p, "issue": "missing from parsed statements"} for p in miss_pdf]
        + [{"period": p, "issue": "missing month in PDF series"} for p in missing_months[:12]]
        + [{"period": p, "issue": "duplicate period"} for p in dup])

    # V2 per-statement reconciliation
    v2 = [{"period": s["period"], "diff": s.get("formula_diff", "")}
          for s in stmts if s.get("formula_diff", "") not in ("", "0.00")]
    add("V2", "Per-statement reconciliation closes", v2,
        "%d statements with a non-zero formula difference" % len(v2), v2)

    # V3 transaction sum vs charges - payments
    sum_by = {}
    for r in summ:
        if r["currency"] in ("", args.base_currency):
            sum_by.setdefault(r["period"], r)
    v3 = []
    for per, r in sum_by.items():
        ch, pay = to_dec(r["charges"]), to_dec(r["payments"])
        if ch is None or pay is None:
            continue
        net = sum((D(t["post_amount"]) for t in by_period[per]), ZERO)
        if not close(net, ch - pay):
            v3.append({"period": per, "txn_net": f(net), "summary_net": f(ch - pay),
                       "diff": f(net - (ch - pay))})
    add("V3", "Transaction rows reconcile to the statement totals", v3,
        "%d of %d reconciliation rows differ" % (len(v3), len(sum_by)), v3)

    # V4 cross-period linkage (recomputed here, not trusted from the parser field)
    v4 = []
    for i in range(1, len(stmts)):
        a = to_dec(stmts[i - 1].get("current_raw"))
        b = to_dec(stmts[i].get("prev_balance_raw"))
        if a is not None and b is not None and not close(a, b):
            v4.append({"period": stmts[i]["period"],
                       "previous_current": f(a), "this_period_prev": f(b), "diff": f(a - b)})
    add("V4", "Cross-period balances link up", v4,
        "%d statements with a linkage gap" % len(v4), v4)

    # V5 full-period closure
    first, last = stmts[0], stmts[-1]
    first_prev = to_dec(first.get("prev_balance_raw"))
    opening = first_prev if first_prev is not None else (
        (to_dec(first.get("current_balance_calc")) or ZERO)
        - sum((D(t["post_amount"]) for t in by_period[first["period"]]), ZERO))
    closing = D(last.get("effective_balance"), None)
    net_all = sum((D(t["post_amount"]) for t in base), ZERO)
    expected = opening + net_all
    v5 = []
    if closing is None or not close(expected, closing):
        v5.append({"opening": f(opening), "sum_net": f(net_all), "expected": f(expected),
                   "actual": f(closing) if closing is not None else "",
                   "diff": f(expected - closing) if closing is not None else ""})
    dump_csv(out / "balance_walk.csv",
             ["period", "opening", "net_transactions", "expected_closing", "reported_closing", "diff"],
             walk_rows(stmts, by_period, opening))
    add("V5", "Full-period ledger closure", v5,
        "opening %s + net %s = %s ; reported closing %s"
        % (f(opening), f(net_all), f(expected), f(closing) if closing is not None else "n/a"), v5)

    # V6 category totals
    cat_sum = sum((D(t["post_amount"]) for t in base), ZERO)
    by_cat = defaultdict(lambda: ZERO)
    for t in base:
        by_cat[t["category"]] += D(t["post_amount"])
    cat_total = sum(by_cat.values(), ZERO)
    v6 = [] if close(cat_sum, cat_total) else [{"total": f(cat_sum), "category_sum": f(cat_total)}]
    add("V6", "Category totals equal transaction total", v6,
        "%d categories" % len(by_cat), v6)

    # V7 contamination
    bad_points = [t for t in txns if any(u in (t.get("summary", "") + t.get("raw_line", ""))
                                         for u in ("积分", "里程")) and D(t["post_amount"]) != ZERO
                  and t["category"] not in ("消费", "慈善捐赠")]
    unknown_cur = sorted({t["currency"] for t in txns
                          if t["currency"] not in (args.base_currency, "美元", "港币", "欧元",
                                                   "其他货币", "CNY", "USD", "HKD", "")})
    v7 = ([{"issue": "points/miles row treated as money", "period": t["period"],
            "amount": t["post_amount"], "summary": t["summary"][:60]} for t in bad_points[:12]]
          + [{"issue": "unknown currency", "currency": c} for c in unknown_cur])
    add("V7", "No non-monetary rows / unknown currencies", v7,
        "%d foreign-currency rows kept separate" % len(foreign), v7)

    gate = "pass" if all(c["passed"] for c in checks) else "fail"
    result = {
        "gate": gate,
        "statement": ("Ledger is closed. Reports may be generated."
                      if gate == "pass" else
                      "BLOCKED: the ledger does not close. Fix the parsing profile or "
                      "obtain the missing statements before producing ANY number."),
        "period_first": p_first, "period_last": p_last,
        "statements": len(stmts), "transactions_base": len(base),
        "transactions_foreign_excluded": len(foreign),
        "opening_balance": f(opening), "closing_balance": f(closing) if closing is not None else "",
        "net_transactions": f(net_all),
        "checks": checks,
    }
    write_json(out / "validation.json", result)
    for c in checks:
        print("[%s] %-4s %-52s %s" % ("OK" if c["passed"] else "FAIL", c["id"],
                                       c["name"], c["detail"]))
        for s in c["samples"][:3]:
            if not c["passed"]:
                print("        ", s)
    print("GATE =", gate.upper())
    if gate != "pass":
        sys.exit(2)


def walk_rows(stmts, by_period, opening):
    rows, running = [], opening
    for s in stmts:
        net = sum((D(t["post_amount"]) for t in by_period[s["period"]]), ZERO)
        exp = running + net
        cur = D(s.get("effective_balance"), None)
        rows.append({"period": s["period"], "opening": f(running),
                     "net_transactions": f(net), "expected_closing": f(exp),
                     "reported_closing": f(cur) if cur is not None else "",
                     "diff": f(exp - cur) if cur is not None else ""})
        running = cur if cur is not None else exp
    return rows


if __name__ == "__main__":
    main()
