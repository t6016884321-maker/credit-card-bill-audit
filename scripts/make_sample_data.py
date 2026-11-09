#!/usr/bin/env python3
"""Generate fully synthetic, anonymised ledger data for a pipeline dry run.

No real card, bank, person or transaction is involved. The generated dataset
is deliberately internally consistent so validate_ledger.py reports gate=pass.

Usage: python3 make_sample_data.py --out ./demo_out --periods 24
"""
from __future__ import annotations

import argparse
import hashlib
from decimal import Decimal
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from common import dump_csv, f, write_json  # noqa: E402

ZERO = Decimal("0")


def months(start, count):
    y, m = map(int, start.split("-"))
    out = []
    for _ in range(count):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./demo_out")
    ap.add_argument("--periods", type=int, default=24)
    ap.add_argument("--start", default="2024-01")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    (out / "pdf").mkdir(parents=True, exist_ok=True)
    periods = months(args.start, args.periods)

    txns, stmts, summ, manifest = [], [], [], []
    prev = ZERO
    line_no = 0
    for idx, per in enumerate(periods):
        charges, payments = ZERO, ZERO
        y, m = map(int, per.split("-"))
        day = "%04d/%02d/03" % (y, m)

        def add(summary, amt, category, date_str=None):
            nonlocal line_no, charges, payments
            line_no += 1
            a = Decimal(str(amt))
            if a >= 0:
                charges += a
            else:
                payments += -a
            txns.append({
                "period": per, "page": 1, "line_no": line_no, "card_last4": "0000",
                "txn_date": date_str or day, "post_date": date_str or day,
                "summary": summary, "amount": f(a), "currency": "人民币",
                "post_amount": f(a), "category": category,
                "raw_line": "%s %s %s 人民币" % (date_str or day, summary, f(a)),
            })

        add("(消费)示例商户-日用品", 2380.50 + idx * 17, "消费")
        add("(消费)示例商户-餐饮", 486.00, "消费")
        if m == 11:
            add("信用卡年费", 800.00, "年费")
        if m == 6:
            add("短信息服务费", 12.00, "增值服务费")
        if idx and prev > 0:
            add("零售利息", (prev * Decimal("0.0075")).quantize(Decimal("0.01")), "利息")
        # repay most, but leave a small revolving balance
        to_pay = float(charges) * 0.82
        add("转帐还款", -round(to_pay, 2), "还款")

        net = charges - payments
        current = prev + net
        summ.append({
            "period": per, "currency": "人民币", "prev": f(prev),
            "charges": f(charges), "payments": f(payments), "current": f(current),
            "is_deposit": 0,
        })
        limit = "46000.00" if idx < 12 else "50000.00"
        stmts.append({
            "period": per, "cycle_start": "%04d/%02d/01" % (y, m),
            "cycle_end": "%04d/%02d/%02d" % (y, m, 28),
            "card_last4": "0000", "credit_limit": limit,
            "current_balance": f(current), "min_payment": f(current / 10),
            "due_date": "%04d/%02d/18" % (y, (m % 12) + 1), "deposit": "",
            "prev_balance_raw": f(prev), "charges_raw": f(charges),
            "payments_raw": f(payments), "current_raw": f(current),
            "is_deposit": 0, "formula_diff": "0.00", "balance_cross_diff": "0.00",
            "prev_link_diff": "0.00", "effective_balance": f(current),
            "txn_count": sum(1 for t in txns if t["period"] == per),
            "page_count": 2, "file": per + ".pdf",
        })
        manifest.append({
            "period": per, "mail_id": str(1000 + idx),
            "subject": "示例银行 %04d年%02d月 对账单（合成数据）" % (y, m),
            "original": per + ".pdf", "bytes": 12345,
            "sha256": hashlib.sha256(per.encode()).hexdigest(),
        })
        prev = current

    dump_csv(out / "transactions.csv",
             ["period", "page", "line_no", "card_last4", "txn_date", "post_date",
              "summary", "amount", "currency", "post_amount", "category", "raw_line"], txns)
    dump_csv(out / "statements.csv", list(stmts[0].keys()), stmts)
    dump_csv(out / "summary_all.csv", list(summ[0].keys()), summ)
    dump_csv(out / "manifest.csv", list(manifest[0].keys()), manifest)
    dump_csv(out / "installments.csv",
             ["period", "page", "line_no", "principal_due", "interest_due", "remaining_principal"], [])
    write_json(out / "isolation_report.json", {
        "total_messages_scanned": len(periods) + 7,
        "selected_statements": len(periods),
        "bank_like_excluded": 7,
        "duplicate_periods": 0,
        "excluded_samples": [{"date": "2024-01-02", "from": "other-bank@example.com",
                              "subject": "另一家银行电子账单", "reason": "sender filter"}],
        "sender_filter": ["example-bank.com"],
        "subject_filter": ["对账单"],
        "received_since": "全部",
        "note": "SYNTHETIC DEMO DATA — no real mailbox was accessed.",
    })
    write_json(out / "parse_report.json", {
        "profile": "synthetic-demo", "pdf_files": len(periods),
        "statements": len(periods), "transactions": len(txns),
        "period_first": periods[0], "period_last": periods[-1],
        "missing_periods": [], "duplicate_periods": [],
    })
    write_json(out / "fetch_report.json", {"pdf_files": len(periods), "errors": [],
                                           "note": "synthetic demo"})
    print("Synthetic dataset: %d periods, %d transactions -> %s" % (len(periods), len(txns), out))
    print("Closing balance:", f(prev))
    print("This is demo data only. No real statements, accounts or credentials were used.")


if __name__ == "__main__":
    main()
