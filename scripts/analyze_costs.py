#!/usr/bin/env python3
"""Step 4 — Multi-definition cost accounting.

Answers five DIFFERENT questions that are routinely confused:
  1. gross consumption       — total purchase flow (not what you paid)
  2. net consumption         — after returns / reversals
  3. total bank fees+interest — the real cost of using the card
  4. economic spend          — net consumption + bank costs
  5. actual repayments       — cash that left your bank account

Also computes: category/year breakdown, implied daily interest rate per period,
instalment IRR, and the 3-year statute-of-limitations split.

Refuses to run unless validation.json says gate=pass.

Usage: python3 analyze_costs.py --out ./audit_out --as-of 2026-11-09
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (D, ZERO, annualized_from_monthly, dump_csv, f, money,  # noqa: E402
                    month_irr, read_csv, read_json, to_dec, write_json)

FEE_CATS = {"年费", "利息", "分期手续费", "其他手续费", "滞纳金", "违约金",
            "超限费", "增值服务费"}
CONSUME_CATS = {"消费", "慈善捐赠", "退货退款", "其他冲账"}
CATS = sorted(FEE_CATS | CONSUME_CATS | {"还款", "分期本金", "取现", "溢缴款"})

CONTRACT_RES = [
    re.compile(r"(?:自动消费分期|账单分期|消费分期|邮购分期|财智金)\D{0,6}(\d{8,})\s*/\s*(\d{1,2})"),
    re.compile(r"(\d{10,})\s*/\s*(\d{1,2})"),
]


def d(s):
    return D(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./audit_out")
    ap.add_argument("--base-currency", default="人民币")
    ap.add_argument("--as-of", default=date.today().isoformat(),
                    help="reference date for the 3-year limitation split, YYYY-MM-DD")
    ap.add_argument("--limit-years", type=int, default=3)
    args = ap.parse_args()
    out = Path(args.out).resolve()
    val = read_json(out / "validation.json", {})
    if val.get("gate") != "pass":
        sys.exit("BLOCKED: validation gate is not 'pass'. Run validate_ledger.py and fix the ledger first.")

    txns = read_csv(out / "transactions.csv")
    stmts = sorted(read_csv(out / "statements.csv"), key=lambda r: r["period"])
    insts = read_csv(out / "installments.csv")
    base = [t for t in txns if t["currency"] == args.base_currency]
    by_period = defaultdict(list)
    for t in base:
        by_period[t["period"]].append(t)

    # --- category totals -------------------------------------------------
    cat = defaultdict(lambda: [0, ZERO])
    for t in base:
        c = t["category"]
        cat[c][0] += 1
        cat[c][1] += d(t["post_amount"])
    cat_rows = [{"category": c, "count": n, "amount": f(v)}
                for c, (n, v) in sorted(cat.items(), key=lambda x: -abs(x[1][1]))]
    dump_csv(out / "category_summary.csv", ["category", "count", "amount"], cat_rows)

    gross = cat["消费"][1] + cat["慈善捐赠"][1]
    returns = cat["退货退款"][1] + cat["其他冲账"][1]
    net = gross + returns
    fee_total = sum((cat[c][1] for c in FEE_CATS), ZERO)
    repay = -cat["还款"][1]
    econ = net + fee_total
    closing = d(val.get("closing_balance"))
    cost_pct = (fee_total / net * 100) if net else ZERO

    # --- fees by type ----------------------------------------------------
    fee_txns = [t for t in base if t["category"] in FEE_CATS]
    dump_csv(out / "fee_detail.csv",
             ["period", "txn_date", "summary", "post_amount", "category", "page", "line_no"],
             [{k: t.get(k, "") for k in ("period", "txn_date", "summary", "post_amount",
                                         "category", "page", "line_no")} for t in fee_txns])
    fee_by_type = {c: {"count": cat[c][0], "amount": f(cat[c][1])} for c in sorted(FEE_CATS)}

    annual_fee_rows = [t for t in base if t["category"] == "年费"]
    af_charged = sum((d(t["post_amount"]) for t in annual_fee_rows if d(t["post_amount"]) > 0), ZERO)
    af_refund = -sum((d(t["post_amount"]) for t in annual_fee_rows if d(t["post_amount"]) < 0), ZERO)

    interest_rows = [t for t in base if t["category"] == "利息"]
    interest_by_summary = defaultdict(lambda: [0, ZERO])
    for t in interest_rows:
        k = t["summary"][:40]
        interest_by_summary[k][0] += 1
        interest_by_summary[k][1] += d(t["post_amount"])
    interest_split = [{"summary": k, "count": n, "amount": f(v)}
                      for k, (n, v) in sorted(interest_by_summary.items(),
                                              key=lambda x: -abs(x[1][1]))]

    # --- year table ------------------------------------------------------
    ycat = defaultdict(lambda: defaultdict(lambda: ZERO))
    yperiods = defaultdict(int)
    for t in base:
        ycat[t["period"][:4]][t["category"]] += d(t["post_amount"])
        yperiods[t["period"][:4]] += 1
    for s in stmts:
        yperiods.setdefault(s["period"][:4], 0)
    stmt_by_year = {}
    for s in stmts:
        stmt_by_year[s["period"][:4]] = s
    year_rows = []
    for y in sorted(yperiods):
        c = ycat[y]
        g = c["消费"] + c["慈善捐赠"]
        n = g + c["退货退款"] + c["其他冲账"]
        fees = sum((c[k] for k in FEE_CATS), ZERO)
        s_last = stmt_by_year.get(y)
        bal = d(s_last.get("effective_balance")) if s_last else ZERO
        year_rows.append({
            "year": y, "periods": sum(1 for s in stmts if s["period"].startswith(y)),
            "gross": f(g), "net": f(n), "fees": f(fees),
            "repayment": f(-c["还款"]), "closing": f(bal),
            "cost_pct": f(fees / n * 100) if n else "0.00",
            "interest": f(c["利息"]), "annual_fee": f(c["年费"]),
        })
    dump_csv(out / "annual_summary.csv",
             ["year", "periods", "gross", "net", "fees", "repayment", "closing",
              "cost_pct", "interest", "annual_fee"], year_rows)

    # --- implied daily interest rate ------------------------------------
    diag = []
    for s in stmts:
        interest = sum((d(t["post_amount"]) for t in by_period[s["period"]]
                        if t["category"] == "利息"), ZERO)
        prev = to_dec(s.get("prev_balance_raw"))
        if interest <= 0 or prev is None or prev <= 0:
            continue
        days = 30
        try:
            a, b = s.get("cycle_start", ""), s.get("cycle_end", "")
            if a and b:
                fmt = "%Y/%m/%d" if "/" in a else "%Y-%m-%d"
                from datetime import datetime
                days = max(1, (datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).days)
        except Exception:
            pass
        rate = (interest / prev / Decimal(days)) * 1000  # per mille per day
        diag.append({"period": s["period"], "interest": f(interest), "prev_balance": f(prev),
                     "days": days, "implied_daily_per_mille": f(rate),
                     "above_0_5": int(rate > Decimal("0.5")),
                     "note": "Approximation only. Requires the bank's daily accrual detail to confirm."})
    dump_csv(out / "interest_diagnostics.csv",
             ["period", "interest", "prev_balance", "days", "implied_daily_per_mille",
              "above_0_5", "note"], diag)

    # --- instalment contracts and IRR ------------------------------------
    contracts = defaultdict(lambda: {"principal": ZERO, "fee": ZERO, "periods": [],
                                    "instalments": set(), "kind": set()})
    for t in base:
        for pat in CONTRACT_RES:
            m = pat.search(t["summary"])
            if not m:
                continue
            c = contracts[m.group(1)]
            c["periods"].append(t["period"])
            c["instalments"].add(int(m.group(2)))
            c["kind"].add(t["category"])
            if t["category"] in ("利息", "分期手续费"):
                c["fee"] += d(t["post_amount"])
            elif t["category"] == "分期本金":
                c["principal"] += d(t["post_amount"])
            break
    auto_rows = []
    for cid, c in contracts.items():
        p = abs(c["principal"])
        n = max(c["instalments"]) if c["instalments"] else 0
        fee = c["fee"]
        # Cash-flow view: borrow p at t0, repay (p+fee)/n each month.
        monthly = (p + fee) / Decimal(n) if n and p else ZERO
        irr = month_irr([float(p)] + [-float(monthly)] * n) if n and p else None
        annual = annualized_from_monthly(irr)
        auto_rows.append({
            "contract": cid, "first": min(c["periods"]), "last": max(c["periods"]),
            "instalments": n, "principal": f(p), "fee": f(fee),
            "nominal_rate_pct": f(fee / p * 100) if p else "0.00",
            "irr_annual_compound_pct": f(Decimal(str(annual))) if annual is not None else "",
            "fee_naming": "/".join(sorted(c["kind"])),
        })
    auto_rows.sort(key=lambda r: r["first"])
    dump_csv(out / "installment_contracts.csv",
             ["contract", "first", "last", "instalments", "principal", "fee",
              "nominal_rate_pct", "irr_annual_compound_pct", "fee_naming"], auto_rows)

    # --- behaviour + statute --------------------------------------------
    indebted = sum(1 for s in stmts if d(s.get("effective_balance")) > ZERO)
    asof = date.fromisoformat(args.as_of)
    try:
        cutoff = asof.replace(year=asof.year - args.limit_years).isoformat()
    except ValueError:
        cutoff = asof.replace(year=asof.year - args.limit_years, day=28).isoformat()
    cutoff_period = cutoff[:7]
    in_limit = sum((d(t["post_amount"]) for t in fee_txns if t["period"] >= cutoff_period), ZERO)
    out_limit = fee_total - in_limit

    analysis = {
        "meta": {
            "as_of": args.as_of, "limitation_years": args.limit_years,
            "statute_cutoff_period": cutoff_period,
            "period_first": val.get("period_first"), "period_last": val.get("period_last"),
            "statements": len(stmts), "transactions_base": len(base),
            "base_currency": args.base_currency,
            "foreign_rows_excluded": len(txns) - len(base),
        },
        "totals": {
            "gross_consumption": f(gross), "returns_and_reversals": f(returns),
            "net_consumption": f(net), "bank_fees_and_interest": f(fee_total),
            "economic_spend": f(econ), "actual_repayment": f(repay),
            "closing_balance": f(closing), "cost_rate_pct": f(cost_pct),
            "annual_fee_charged": f(af_charged), "annual_fee_refunded": f(af_refund),
            "annual_fee_net": f(af_charged - af_refund),
            "interest_total": f(sum((d(t["post_amount"]) for t in interest_rows), ZERO)),
            "installment_principal": f(cat["分期本金"][1]),
        },
        "category_summary": cat_rows,
        "fee_by_type": fee_by_type,
        "interest_split": interest_split,
        "year_rows": year_rows,
        "interest_diagnostics": {
            "count": len(diag),
            "above_0_5_count": sum(1 for r in diag if r["above_0_5"]),
            "rows": diag[:20],
        },
        "installment_contracts": auto_rows,
        "annual_fee_rows": [{k: t.get(k, "") for k in
                             ("period", "txn_date", "post_amount", "summary")}
                            for t in annual_fee_rows],
        "behaviour": {
            "indebted_periods": indebted, "total_periods": len(stmts),
            "indebted_pct": f(Decimal(indebted) / Decimal(len(stmts)) * 100) if stmts else "0.00",
            "periods_with_repayment": sum(1 for s in stmts
                                          if any(t["category"] == "还款"
                                                 for t in by_period[s["period"]])),
            "note": "期末长期保有欠款，说明绝大多数账期没有享受免息期，"
                    "这是循环利息最主要的成因。",
        },
        "statute": {
            "cutoff": cutoff, "fees_within_limit": f(in_limit),
            "fees_outside_limit": f(out_limit),
            "note": "Amounts outside the limitation period are NOT automatically unrecoverable "
                    "in negotiation, but a court defence is likely. Never present them as "
                    "legally refundable without a lawyer's opinion.",
        },
        "installment_table_rows": len(insts),
    }
    write_json(out / "analysis.json", analysis)
    print("Analysis written -> %s" % (out / "analysis.json"))
    print("  gross %s | net %s | fees %s | repayment %s | closing %s"
          % (money(gross), money(net), money(fee_total), money(repay), money(closing)))
    print("  annual fee net %s | interest %s | cost rate %s%%"
          % (money(af_charged - af_refund),
             money(sum((d(t["post_amount"]) for t in interest_rows), ZERO)), f(cost_pct)))
    print("  %d/%d periods carried a balance; fees within %d-year limit %s"
          % (indebted, len(stmts), args.limit_years, money(in_limit)))


if __name__ == "__main__":
    main()
