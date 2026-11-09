#!/usr/bin/env python3
"""Step 2b — Parse statement PDFs into a structured, auditable ledger.

Reconstructs table rows from word coordinates (not from the PDF text stream,
where labels and values are often interleaved). All amounts stay as Decimal
with their original two decimals.

Four traps that this parser deliberately handles — each one previously caused
a wrong total in a real 192-statement audit:
  1. Points rows such as "境外促销赠积分 -48,000.00 积分" look exactly like money.
  2. Foreign-currency rows sit next to CNY rows in the reconciliation table.
  3. "无欠款" usually means an overpayment (negative balance), not zero.
  4. "分期冲帐" reverses the original purchase when an instalment is created;
     it is not an early settlement and must not be reclassified as a refund.

Usage:
  python3 parse_statements.py --out ./audit_out \
      --profile ../assets/profiles/cgb_classic_platinum.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from common import dump_csv, f, period_range, to_dec, write_json  # noqa: E402

AMT_PREFIX = re.compile(r"^-?\d{1,3}(?:,\d{3})*\.\d{2}")

DEFAULT_ASSETS = Path(__file__).parent.parent / "assets" / "profiles"

CATEGORY_RULES = [
    ("年费", ("年费",), "年费"),
    ("滞纳金", ("滞纳金",), "滞纳金"),
    ("违约金", ("违约金",), "违约金"),
    ("超限费", ("超限费",), "超限费"),
    ("分期手续费", ("手续费",), "分期手续费"),
    ("其他手续费", ("手续费",), "其他手续费"),
    ("利息", ("利息", "罚息", "复利"), "利息"),
    ("还款", ("还款", "转帐还款", "转账还款"), "还款"),
    ("退货退款", ("退货", "退款", "返还", "冲正"), "退货退款"),
    ("慈善捐赠", ("捐赠",), "慈善捐赠"),
    ("增值服务费", ("短信", "保险", "权益", "增值服务", "保障服务"), "增值服务费"),
    ("取现", ("取现", "提现", "预借现金"), "取现"),
    ("分期本金", ("分期", "样样行", "财智金"), "分期本金"),
]


def classify(summary, amount, rules=None, neg_category="其他冲账"):
    s = (summary or "").strip()
    neg = amount is not None and amount < 0
    tagged_consumption = s.startswith("(消费)")
    for name, kws, cat in (rules or CATEGORY_RULES):
        if any(k in s for k in kws):
            if name == "分期手续费":
                return "分期手续费" if any(k in s for k in ("分期", "样样行", "财智金")) else "其他手续费"
            if name == "其他手续费" and any(k in s for k in ("分期", "样样行", "财智金")):
                return "分期手续费"
            if name == "增值服务费" and tagged_consumption:
                return "消费"       # "(消费)…保险经纪" is a purchase, not a bank fee
            return cat
    if neg:
        return neg_category
    if "存款" in s or "溢缴" in s:
        return "溢缴款"
    return "消费"


def lines_of_page(page, y_tol=2.6):
    words = sorted(page.get_text("words"), key=lambda w: (w[1], w[0]))
    lines, cur, base_y = [], [], None
    for w in words:
        if base_y is None or abs(w[1] - base_y) <= y_tol:
            if base_y is None:
                base_y = w[1]
            cur.append(w)
        else:
            lines.append(sorted(cur, key=lambda x: x[0]))
            cur, base_y = [w], w[1]
    if cur:
        lines.append(sorted(cur, key=lambda x: x[0]))
    return lines


def line_text(ln):
    return " ".join(w[4].strip() for w in ln if w[4].strip())


def load_profile(path):
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = DEFAULT_ASSETS / (str(path) + ".json" if not str(path).endswith(".json") else str(path))
    cfg = json.loads(Path(p).read_text(encoding="utf-8"))
    cfg.setdefault("base_currency", "人民币")
    cfg.setdefault("currencies", ["人民币", "美元", "港币", "欧元"])
    cfg.setdefault("non_money_units", ["积分", "里程"])
    cfg.setdefault("deposit_marker", "存款")
    cfg.setdefault("markers", {})
    cfg.setdefault("columns", {})
    cfg.setdefault("summary", {"currency_x0_max": 140, "min_amounts": 4, "take_last": 4})
    cfg.setdefault("date_re", r"^\d{4}[-/]\d{2}[-/]\d{2}$")
    return cfg


def infer_columns(pdf_dir, limit=25):
    """Cluster right-aligned amount x1 positions over a sample of PDFs."""
    xs = []
    for fp in sorted(pdf_dir.glob("*.pdf"))[:limit]:
        try:
            d = pymupdf.open(fp)
        except Exception:
            continue
        for page in d:
            for w in page.get_text("words"):
                if AMT_PREFIX.match(w[4].strip()):
                    xs.append(round(w[2]))
        d.close()
    if not xs:
        return {}
    c = Counter(int(x // 12) * 12 for x in xs)
    strong = [b for b, n in c.most_common(8) if n >= max(3, len(xs) // 80)]
    strong = sorted(set(strong))
    cols = {"inferred": True, "clusters": c.most_common(8)}
    if len(strong) >= 2:
        cols["trade_x1"] = [strong[-2] - 5, strong[-2] + 16]
        cols["post_x1"] = [strong[-1] - 5, strong[-1] + 16]
    else:
        cols["post_x1"] = [strong[-1] - 5, strong[-1] + 16]
    cols["currency_x0_min"] = (strong[-1] + 18) if strong else 525
    cols["summary_x0_max"] = (strong[0] - 45) if strong else 350
    return cols


def in_range(x, bounds):
    return bounds and len(bounds) == 2 and bounds[0] is not None and bounds[0] <= x < bounds[1]


def parse_account_info(ln, info, cfg):
    txt = line_text(ln)
    cols = cfg["columns"].get("account", {})
    if not cols:
        return
    if "账单周期" in txt or "Statement Cycle" in txt:
        dr = re.compile(cfg["date_re"])
        ds = [w[4].strip() for w in ln if dr.match(w[4].strip())]
        if len(ds) >= 2:
            info["cycle_start"], info["cycle_end"] = ds[0], ds[1]
        return
    if not any(w[4].strip() == cfg["base_currency"] and
               in_range(w[0], cols.get("currency")) for w in ln):
        return
    if len(ln) < 6 or info.get("card_last4"):
        return
    vals = {}
    for w in ln:
        x, t = w[0], w[4].strip()
        for key, bounds in cols.items():
            if in_range(x, bounds) and key not in vals:
                vals[key] = t
    for key in cols:
        info[key] = vals.get(key, "")


def parse_txn_line(ln, period, page_no, line_no, card, cfg):
    txt = line_text(ln)
    cols = cfg["columns"]
    dr = re.compile(cfg["date_re"])
    if not txt or ("交易日期" in txt and "入账日期" in txt):
        return None
    if txt.startswith("卡号：") or ("交易明细" in txt and len(ln) <= 2):
        return None
    amt_words = [w for w in ln if AMT_PREFIX.match(w[4].strip())]
    if not amt_words:
        return None

    # Trap 1: non-monetary units (points / miles) must never enter the ledger.
    x_min = cols.get("currency_x0_min")
    right = [w for w in ln if x_min is not None and w[0] > x_min]
    right_word = right[0][4].strip() if right else ""
    if right_word and right_word not in cfg["currencies"]:
        return None
    if any(u in txt for u in cfg["non_money_units"]) and not any(
            c in right_word for c in cfg["currencies"]):
        return None

    trade = [w for w in amt_words if in_range(w[2], cols.get("trade_x1"))]
    posted = [w for w in amt_words if in_range(w[2], cols.get("post_x1"))]
    if not posted and not trade:
        return None
    trade_amt = to_dec(trade[0][4]) if trade else None
    post_amt = to_dec(posted[0][4]) if posted else trade_amt
    if post_amt is None:
        return None

    dates = [w[4].strip() for w in ln if dr.match(w[4].strip())]
    txn_date = dates[0] if dates else ""
    post_date = dates[1] if len(dates) > 1 else txn_date
    used = set(id(w) for w in trade + posted)
    skip = set(cfg["currencies"])
    parts = []
    for w in ln:
        t = w[4].strip()
        if id(w) in used or not t or t in skip or dr.match(t) or AMT_PREFIX.match(t):
            continue
        if cols.get("summary_x0_max") and w[0] > cols["summary_x0_max"]:
            continue
        parts.append(t)
    summary = " ".join(parts).strip()

    # Trap 2: the currency column is the RIGHTMOST one. Never infer currency
    # from a currency word appearing anywhere in the row.
    cur_words = [w for w in ln if x_min is not None and w[0] > x_min
                 and w[4].strip() in cfg["currencies"]]
    currency = cur_words[0][4].strip() if cur_words else cfg["base_currency"]
    return {
        "period": period, "page": page_no + 1, "line_no": line_no,
        "card_last4": card, "txn_date": txn_date, "post_date": post_date,
        "summary": summary, "amount": f(trade_amt), "currency": currency,
        "post_amount": f(post_amt), "category": classify(summary, post_amt),
        "raw_line": txt[:400],
    }


def parse_summary_line(ln, cfg):
    """Reconciliation row: prev + charges - payments = current."""
    s = cfg["summary"]
    amts = [w for w in ln if AMT_PREFIX.match(w[4].strip())]
    if len(amts) < s.get("min_amounts", 4):
        return None
    amts.sort(key=lambda w: w[0])
    chosen = amts[-s.get("take_last", 4):]
    currency = ""
    for w in ln:
        if w[0] < s.get("currency_x0_max", 140) and w[4].strip() in cfg["currencies"]:
            currency = w[4].strip()
            break
    return {
        "currency": currency,
        "prev_balance_raw": chosen[0][4], "charges_raw": chosen[1][4],
        "payments_raw": chosen[2][4], "current_raw": chosen[3][4],
        "prev_balance": to_dec(chosen[0][4]), "charges": to_dec(chosen[1][4]),
        "payments": to_dec(chosen[2][4]), "current_balance_calc": to_dec(chosen[3][4]),
        "is_deposit": int(cfg["deposit_marker"] in chosen[3][4]),
    }


def marker_match(txt, cfg, key, require_all=False):
    vals = cfg["markers"].get(key, [])
    if not vals:
        return False
    return all(v in txt for v in vals) if require_all else any(v in txt for v in vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./audit_out")
    ap.add_argument("--pdf-dir", default="")
    ap.add_argument("--profile", default="generic")
    ap.add_argument("--limit", type=int, default=0, help="parse only the first N PDFs (debugging)")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    pdf_dir = Path(args.pdf_dir).resolve() if args.pdf_dir else out / "pdf"
    cfg = load_profile(args.profile)
    if not cfg["columns"] or cfg.get("infer_columns"):
        inferred = infer_columns(pdf_dir)
        inferred.pop("clusters", None)
        cfg["columns"] = {**inferred, **{k: v for k, v in cfg["columns"].items() if v}}
        write_json(out / "inferred_columns.json", inferred)
    files = sorted(pdf_dir.glob("*.pdf"))
    if args.limit:
        files = files[:args.limit]
    if not files:
        raise SystemExit("No PDFs in %s" % pdf_dir)

    txns, stmts, insts, problems = [], [], [], []
    for fp in files:
        period = fp.stem
        try:
            doc = pymupdf.open(fp)
            if doc.needs_pass:
                raise RuntimeError("password-protected PDF")
        except Exception as ex:
            problems.append({"period": period, "stage": "open", "msg": str(ex)[:160]})
            continue
        info = {"period": period, "page_count": doc.page_count, "file": fp.name}
        mode, card = None, ""
        for pno in range(doc.page_count):
            for lno, ln in enumerate(lines_of_page(doc[pno]), 1):
                txt = line_text(ln)
                if not txt:
                    continue
                if pno == 0:
                    parse_account_info(ln, info, cfg)
                if marker_match(txt, cfg, "txn_all", True) or marker_match(txt, cfg, "txn_any"):
                    mode = "txn"
                    continue
                if marker_match(txt, cfg, "summary_any"):
                    mode = "summary"
                    continue
                if marker_match(txt, cfg, "installment_any"):
                    mode = "installment"
                    continue
                if marker_match(txt, cfg, "stop_any"):
                    mode = None
                    continue
                if txt.startswith("注：") or txt.startswith("注:"):
                    continue
                if mode == "txn":
                    if txt.startswith("卡号："):
                        m = re.search(r"(\d{4})\s*$", txt)
                        if m:
                            card = m.group(1)
                        continue
                    r = parse_txn_line(ln, period, pno, lno, card, cfg)
                    if r:
                        txns.append(r)
                elif mode == "summary":
                    rec = parse_summary_line(ln, cfg)
                    if rec:
                        info.setdefault("summary_rows", []).append(rec)
                        if not info.get("prev_balance_raw") and rec["currency"] in ("", cfg["base_currency"]):
                            info.update({k: v for k, v in rec.items() if k != "currency"})
                elif mode == "installment" and txt.startswith("合计"):
                    amts = [w[4] for w in ln if AMT_PREFIX.match(w[4].strip())]
                    if len(amts) >= 3:
                        insts.append({"period": period, "page": pno + 1, "line_no": lno,
                                      "principal_due": amts[-3], "interest_due": amts[-2],
                                      "remaining_principal": amts[-1]})
        pb, ch, pay, cur = (info.get("prev_balance"), info.get("charges"),
                            info.get("payments"), info.get("current_balance_calc"))
        info["formula_diff"] = f(pb + ch - pay - cur) if None not in (pb, ch, pay, cur) else ""
        if info["formula_diff"] == "":
            problems.append({"period": period, "stage": "summary", "msg": "reconciliation row not found"})
        cb = to_dec(info.get("current_balance", ""))
        info["balance_cross_diff"] = f(cb - cur) if (cb is not None and cur is not None) else ""
        # Trap 3: "无欠款" is an overpayment, i.e. a negative balance.
        if cur is not None:
            info["effective_balance"] = f(cur)
        elif cb is not None:
            info["effective_balance"] = f(cb)
        elif info.get("current_balance") in ("无欠款", "0.00"):
            dep = to_dec(info.get("deposit", ""))
            info["effective_balance"] = f(-dep) if dep and dep > 0 else "0.00"
        else:
            info["effective_balance"] = ""
        info["txn_count"] = sum(1 for t in txns if t["period"] == period)
        stmts.append(info)
        doc.close()

    by_period = {s["period"]: s for s in stmts}
    periods = sorted(by_period)
    for i, p in enumerate(periods):
        by_period[p]["prev_link_diff"] = ""
        if i == 0:
            continue
        a = by_period[periods[i - 1]].get("current_balance_calc")
        b = by_period[p].get("prev_balance")
        if a is not None and b is not None:
            by_period[p]["prev_link_diff"] = f(a - b)

    txn_fields = ["period", "page", "line_no", "card_last4", "txn_date", "post_date",
                  "summary", "amount", "currency", "post_amount", "category", "raw_line"]
    stmt_fields = ["period", "cycle_start", "cycle_end", "card_last4", "credit_limit",
                   "current_balance", "min_payment", "due_date", "deposit",
                   "prev_balance_raw", "charges_raw", "payments_raw", "current_raw",
                   "is_deposit", "formula_diff", "balance_cross_diff", "prev_link_diff",
                   "effective_balance", "txn_count", "page_count", "file"]
    dump_csv(out / "transactions.csv", txn_fields, txns)
    dump_csv(out / "statements.csv", stmt_fields, stmts)
    dump_csv(out / "installments.csv", ["period", "page", "line_no", "principal_due",
                                        "interest_due", "remaining_principal"], insts)
    sum_rows = [{"period": s["period"], "currency": r["currency"],
                 "prev": r["prev_balance_raw"], "charges": r["charges_raw"],
                 "payments": r["payments_raw"], "current": r["current_raw"],
                 "is_deposit": r["is_deposit"]}
                for s in stmts for r in s.get("summary_rows", [])]
    dump_csv(out / "summary_all.csv", ["period", "currency", "prev", "charges",
                                       "payments", "current", "is_deposit"], sum_rows)

    first, last, missing, dup = period_range(periods)
    report = {
        "profile": cfg.get("name", "custom"),
        "inferred_columns": bool(cfg["columns"].get("inferred")),
        "pdf_files": len(files), "statements": len(stmts), "transactions": len(txns),
        "period_first": first, "period_last": last,
        "missing_periods": missing, "duplicate_periods": dup,
        "problem_count": len(problems), "problems": problems[:60],
        "formula_mismatch": [s["period"] for s in stmts if s["formula_diff"] not in ("", "0.00")],
        "prev_link_mismatch": [s["period"] for s in stmts if s["prev_link_diff"] not in ("", "0.00")],
        "balance_cross_mismatch": [s["period"] for s in stmts
                                   if s["balance_cross_diff"] not in ("", "0.00")],
        "category_counts": dict(Counter(t["category"] for t in txns)),
        "currency_counts": dict(Counter(t["currency"] for t in txns)),
    }
    write_json(out / "parse_report.json", report)
    print("Parsed %d PDFs / %d transactions / %d statements (%s -> %s)"
          % (len(files), len(txns), len(stmts), first, last))
    print("Problems: %d | formula mismatch: %d | link mismatch: %d | missing periods: %d"
          % (len(problems), len(report["formula_mismatch"]),
             len(report["prev_link_mismatch"]), len(missing)))
    print("Currencies:", report["currency_counts"])
    print("NEXT: run validate_ledger.py — reports are BLOCKED until the gate passes.")


if __name__ == "__main__":
    main()
