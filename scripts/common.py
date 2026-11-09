#!/usr/bin/env python3
"""Shared helpers for the credit-card-bill-audit pipeline.

Design rules that MUST NOT be broken:
  * All money is Decimal, never float. Original two decimals are preserved.
  * Base currency only; foreign-currency rows are kept but excluded from totals.
  * Credentials are read from environment variables only, never written to disk.
"""
from __future__ import annotations

import csv
import html
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

ZERO = Decimal("0")
TOL = Decimal("0.01")
AMT_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})*\.\d{2}$")


def D(s, default=ZERO):
    """Parse a CSV amount safely."""
    if s is None or s == "":
        return default
    try:
        return Decimal(str(s).replace(",", ""))
    except (InvalidOperation, ValueError):
        return default


def to_dec(s):
    """Parse an amount token from a PDF line.

    '1,234.56' -> Decimal('1234.56')
    '100.78（存款）' -> Decimal('-100.78')  (a credit balance, the bank owes you)
    """
    if s is None:
        return None
    s = str(s).strip()
    m = re.match(r"^-?[\d,]+\.\d{2}", s)
    if not m:
        return None
    try:
        v = Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    return -abs(v) if "存款" in s else v


def f(v):
    return "" if v is None else format(v, ".2f")


def money(v):
    try:
        return "{:,.2f}".format(float(str(v).replace(",", "")))
    except Exception:
        return str(v)


def esc(s):
    return html.escape(str(s), quote=True)


def dump_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def read_csv(path):
    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def period_range(periods):
    """Return (first, last, missing, duplicated) for YYYY-MM strings."""
    if not periods:
        return None, None, [], []
    seen, dup = set(), []
    for p in periods:
        if p in seen:
            dup.append(p)
        seen.add(p)
    ps = sorted(seen)
    first, last = ps[0], ps[-1]
    y, m = map(int, first.split("-"))
    ey, em = map(int, last.split("-"))
    cur, missing = [y, m], []
    while (cur[0], cur[1]) <= (ey, em):
        key = "%04d-%02d" % tuple(cur)
        if key not in seen:
            missing.append(key)
        cur[1] += 1
        if cur[1] == 13:
            cur[0], cur[1] = cur[0] + 1, 1
    return first, last, missing, dup


def month_irr(cashflows, lo=-0.99, hi=1.0, iterations=200):
    """Monthly IRR by bisection on NPV. cashflows[0] is the amount received (positive)."""
    if len(cashflows) < 2:
        return None

    def npv(r):
        return sum(cf / ((1 + r) ** i) for i, cf in enumerate(cashflows))

    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(iterations):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def annualized_from_monthly(r):
    """Compound a monthly IRR into an annual rate, in percent."""
    if r is None:
        return None
    try:
        return (((1 + r) ** 12) - 1) * 100
    except OverflowError:
        return None


def table_html(headers, rows, numcols=(), totalrow=None, widths=None):
    out = ["<table>"]
    if widths:
        out.append("<colgroup>" + "".join(
            '<col style="width:%s">' % w for w in widths) + "</colgroup>")
    out.append("<thead><tr>" + "".join(
        '<th%s>%s</th>' % (' class="num"' if i in numcols else '', esc(h))
        for i, h in enumerate(headers)) + "</tr></thead><tbody>")
    for r in rows:
        out.append("<tr>" + "".join(
            '<td%s>%s</td>' % (' class="num"' if i in numcols else '', str(c))
            for i, c in enumerate(r)) + "</tr>")
    if totalrow:
        out.append('<tr class="total">' + "".join(
            '<td%s>%s</td>' % (' class="num"' if i in numcols else '', str(c))
            for i, c in enumerate(totalrow)) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)
