#!/usr/bin/env python3
"""Step 2a — Probe statement PDFs and suggest a parsing profile.

Run this once on a new bank's statements. It reports:
  * encryption / text-layer availability (a scanned image needs OCR first),
  * page geometry and representative text,
  * section marker candidates,
  * clusters of right-aligned amount x-positions -> suggested column bounds,
  * detected date formats and currency tokens.

The output is a SUGGESTION, not a validated profile. Calibrate it against
at least three statements from different years, then run parse_statements.py
and let validate_ledger.py gate the result.

Usage: python3 profile_statements.py --out ./audit_out [--pdf-dir ./audit_out/pdf]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from common import AMT_RE, write_json  # noqa: E402

DATE_PATTERNS = [
    r"\d{4}/\d{2}/\d{2}", r"\d{4}-\d{2}-\d{2}", r"\d{4}\.\d{2}\.\d{2}",
    r"\d{2}/\d{2}/\d{4}", r"\d{8}",
]
MARKER_HINTS = [
    "交易日期", "入账日期", "交易明细", "本期账单金额", "上期账单金额", "本期应还",
    "最低还款", "信用额度", "分期明细", "积分", "温馨提示", "还款", "消费", "手续费",
    "Previous Balance", "New Balance", "Transaction Date", "Minimum Payment",
]


def cluster_x(values, bin_width=12):
    if not values:
        return []
    buckets = Counter(int(v // bin_width) * bin_width for v in values)
    return [(b, c) for b, c in buckets.most_common(8)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./audit_out")
    ap.add_argument("--pdf-dir", default="")
    ap.add_argument("--samples", type=int, default=6)
    args = ap.parse_args()
    out = Path(args.out).resolve()
    pdf_dir = Path(args.pdf_dir).resolve() if args.pdf_dir else out / "pdf"
    files = sorted(pdf_dir.glob("*.pdf"))
    if not files:
        raise SystemExit("No PDFs found under %s" % pdf_dir)
    picks = [files[0], files[len(files) // 2], files[-1]]
    picks += [f for f in files[1:-1:max(1, len(files) // args.samples)]
              if f not in picks][:args.samples]
    picks = sorted(set(picks))

    amount_x1, date_formats, currencies, markers = [], Counter(), Counter(), Counter()
    page_dims, per_file = set(), []

    for fp in picks:
        try:
            doc = pymupdf.open(fp)
        except Exception as ex:
            per_file.append({"file": fp.name, "error": str(ex)[:150]})
            continue
        info = {
            "file": fp.name, "pages": doc.page_count,
            "encrypted": bool(doc.is_encrypted or doc.needs_pass),
            "text_chars_first_page": len(doc[0].get_text()),
        }
        if doc.needs_pass:
            per_file.append(dict(info, error="PDF is password protected; supply readable originals"))
            doc.close()
            continue
        for page in doc:
            page_dims.add((round(page.rect.width), round(page.rect.height)))
            words = page.get_text("words")
            for w in words:
                t = w[4].strip()
                if AMT_RE.match(t):
                    amount_x1.append(round(w[2], 1))
                if t in ("人民币", "美元", "港币", "欧元", "CNY", "USD", "HKD"):
                    currencies[t] += 1
                for h in MARKER_HINTS:
                    if h in t:
                        markers[h] += 1
            txt = page.get_text()
            for p in DATE_PATTERNS:
                date_formats[p] += len(re.findall(p, txt))
        info["head"] = re.sub(r"\s+", " ", doc[0].get_text()[:420])
        per_file.append(info)
        doc.close()

    clusters = cluster_x(amount_x1)
    # Right-aligned numeric columns cluster tightly; the two largest clusters
    # with enough separation are usually the transaction amount and posted amount.
    strong = [b for b, c in clusters if c >= max(3, len(picks))]
    suggestion = {
        "amount_x1_clusters": [{"x1_bin": b, "count": c} for b, c in clusters],
        "suggested_post_x1": [strong[-1] - 4, strong[-1] + 14] if strong else [None, None],
        "suggested_trade_x1": [strong[-2] - 4, strong[-2] + 14] if len(strong) > 1 else [None, None],
        "suggested_summary_x0_max": (min(strong) - 45) if strong else 350,
        "date_formats_seen": {k: v for k, v in date_formats.items() if v},
        "currency_tokens": dict(currencies),
        "section_marker_hits": dict(markers.most_common(20)),
        "page_dimensions": sorted(page_dims),
    }
    result = {
        "pdf_dir": str(pdf_dir),
        "total_pdfs": len(files),
        "sampled": [p.name for p in picks],
        "files": per_file,
        "suggestion": suggestion,
        "next_steps": [
            "If any file reports encrypted=True or text_chars_first_page < 100, run OCR first (e.g. ocrmypdf) — coordinates cannot be extracted from an image-only PDF.",
            "Copy assets/profiles/cgb_classic_platinum.json or generic.json to a new profile and adjust columns / markers / date_re using the suggestion above.",
            "Parse 3 statements from different years, then run validate_ledger.py. A non-zero gate means the profile is wrong — never hand-wave a mismatch.",
        ],
    }
    write_json(out / "profile_suggestion.json", result)
    print("Sampled %d of %d PDFs -> %s" % (len(picks), len(files), out / "profile_suggestion.json"))
    print("Encrypted / image-only:", [f["file"] for f in per_file
                                      if f.get("encrypted") or f.get("text_chars_first_page", 999) < 100])
    print("Page sizes:", sorted(page_dims))
    print("Amount x1 clusters:", clusters[:6])
    print("Date formats:", {k: v for k, v in date_formats.items() if v})


if __name__ == "__main__":
    main()
