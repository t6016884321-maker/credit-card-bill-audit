#!/usr/bin/env python3
"""Step 1 — Collect credit-card statement PDFs, read-only.

Two input modes:
  A. IMAP mailbox (recommended). Credentials come ONLY from environment variables.
  B. A local folder of manually downloaded / exported PDFs (no credentials needed).

Safety guarantees:
  * IMAP session is opened with readonly=True; every fetch uses BODY.PEEK[],
    so no message is marked as read, moved, deleted or otherwise modified.
  * No credential, token, or mailbox address is written to any output file.
  * An isolation report lists matched AND unmatched bank-like messages so that
    statements from a different bank can never be silently mixed in.

Usage:
  MAIL_USER=... MAIL_TOKEN=... python3 fetch_bills.py \
      --provider qq --sender your-bank.com --subject 对账单 --out ./audit_out

  python3 fetch_bills.py --from-dir ~/Downloads/statements --out ./audit_out
"""
from __future__ import annotations

import argparse
import csv
import email
import hashlib
import imaplib
import os
import re
import socket
import sys
from email import policy
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import dump_csv, write_json  # noqa: E402

PROVIDERS = {
    "qq": ("imap.qq.com", 993),
    "163": ("imap.163.com", 993),
    "126": ("imap.126.com", 993),
    "gmail": ("imap.gmail.com", 993),
    "outlook": ("outlook.office365.com", 993),
    "sina": ("imap.sina.com", 993),
    "exmail": ("imap.exmail.qq.com", 993),
}

PERIOD_PATTERNS = [
    re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月"),
    re.compile(r"(20\d{2})[-/.](\d{1,2})(?:\D|$)"),
    re.compile(r"(20\d{2})(0[1-9]|1[0-2])(?:\D|$)"),
]

BANK_WORDS = ("银行", "信用卡", "对账单", "账单", "credit", "statement", "bank", "card")


def decode(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return str(v or "")


def period_of(text):
    for pat in PERIOD_PATTERNS:
        m = pat.search(text or "")
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            if 2000 <= y <= 2100 and 1 <= mo <= 12:
                return "%04d-%02d" % (y, mo)
    return ""


def boxname(raw):
    s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    m = re.search(r'"([^"]+)"\s*$', s)
    return m.group(1) if m else "INBOX"


def scan_mail(args):
    user = os.environ.get(args.user_env, "").strip()
    token = os.environ.get(args.token_env, "").strip()
    if not user or not token:
        sys.exit("Missing credentials. Export %s and %s as environment variables "
                 "(never pass them as CLI arguments — those leak into shell history)."
                 % (args.user_env, args.token_env))
    host, port = PROVIDERS[args.provider] if args.provider in PROVIDERS \
        else (args.host, args.port)
    if not host:
        sys.exit("Unknown provider; supply --host and --port.")

    socket.setdefaulttimeout(args.timeout)
    print("Connecting to %s:%s ..." % (host, port), flush=True)
    M = imaplib.IMAP4_SSL(host, port)
    M.login(user, token)
    typ, boxes = M.list()
    if typ != "OK":
        sys.exit("Cannot list mailbox folders")
    folder_names = [boxname(b) for b in (boxes or [])]
    if args.folder:
        folder_names = [b for b in folder_names if b in args.folder]
    elif args.folders == "inbox":
        folder_names = [b for b in folder_names if b.upper() == "INBOX"] or ["INBOX"]

    rows = []
    for name in folder_names:
        typ, _ = M.select('"%s"' % name, readonly=True)
        if typ != "OK":
            print("  skip folder %s" % name, flush=True)
            continue
        typ, data = M.search(None, "ALL")
        ids = data[0].split() if typ == "OK" else []
        print("  folder %-28s %5d messages" % (name, len(ids)), flush=True)
        for start in range(0, len(ids), 200):
            seq = b",".join(ids[start:start + 200]).decode()
            typ, chunk = M.fetch(seq, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK":
                continue
            for item in chunk:
                if not (isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bytes)):
                    continue
                h = email.message_from_bytes(item[1])
                subj, frm, dt = decode(h.get("Subject")), decode(h.get("From")), h.get("Date") or ""
                try:
                    iso = parsedate_to_datetime(dt).astimezone().isoformat()
                except Exception:
                    iso = ""
                m = re.match(rb"(\d+)\s", item[0])
                rows.append({
                    "folder": name, "id": m.group(1).decode() if m else "",
                    "date": iso, "from": frm, "subject": subj,
                })
    # Keep the connection open for the download pass; return it with the index.
    return M, rows


def classify(rows, args):
    """Split messages into selected statements, and everything bank-like but excluded."""
    selected, excluded, other = [], [], []
    for r in rows:
        blob = (r["from"] + " " + r["subject"]).lower()
        sender_ok = any(s.lower() in blob for s in args.sender) if args.sender else True
        subject_ok = any(s.lower() in r["subject"].lower() for s in args.subject) \
            if args.subject else True
        date_ok = (not args.since) or r["date"][:10] >= args.since
        per = period_of(r["subject"]) or period_of(r["from"])
        looks_bank = any(w in (r["from"] + r["subject"]).lower() for w in BANK_WORDS)
        if sender_ok and subject_ok and date_ok and per:
            selected.append(dict(r, period=per))
        elif looks_bank:
            excluded.append(dict(r, reason="sender/subject/date/period filter"))
        else:
            other.append(r)
    # Duplicate periods are a real risk when the bank re-sends statements.
    seen, dedup, dup = {}, [], []
    for r in sorted(selected, key=lambda x: x["date"]):
        if r["period"] in seen:
            dup.append(r)
        else:
            seen[r["period"]] = r
            dedup.append(r)
    return dedup, excluded, dup


def download(M, targets, out):
    pdf_dir = out / "pdf"
    raw_dir = out / "eml"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest, errors = [], []
    for i, r in enumerate(targets, 1):
        pdf_path = pdf_dir / (r["period"] + ".pdf")
        if pdf_path.exists() and pdf_path.stat().st_size > 3000 and not args_force:
            b = pdf_path.read_bytes()
            manifest.append(dict(period=r["period"], mail_id=r["id"], subject=r["subject"],
                                 original="(cached)", bytes=len(b),
                                 sha256=hashlib.sha256(b).hexdigest()))
            continue
        try:
            if r["folder"] != CURRENT_FOLDER[0]:
                M.select('"%s"' % r["folder"], readonly=True)
                CURRENT_FOLDER[0] = r["folder"]
            typ, data = M.fetch(r["id"].encode(), "(BODY.PEEK[])")
            if typ != "OK" or not data or not data[0]:
                raise RuntimeError("FETCH failed: %s" % typ)
            raw = data[0][1]
            (raw_dir / (r["period"] + ".eml")).write_bytes(raw)
            msg = email.message_from_bytes(raw, policy=policy.default)
            pdf_bytes, orig = b"", ""
            for part in msg.walk():
                payload = part.get_payload(decode=True) or b""
                fname = part.get_filename() or ""
                disp = part.get_content_disposition() or ""
                is_att = disp == "attachment" or bool(fname)
                if is_att and payload and (
                        part.get_content_type() == "application/pdf"
                        or fname.lower().endswith(".pdf")):
                    if len(payload) > len(pdf_bytes):
                        pdf_bytes, orig = payload, decode(fname)
            if len(pdf_bytes) < 2000:
                raise RuntimeError("no usable PDF attachment")
            pdf_path.write_bytes(pdf_bytes)
            manifest.append(dict(period=r["period"], mail_id=r["id"], subject=r["subject"],
                                 original=orig, bytes=len(pdf_bytes),
                                 sha256=hashlib.sha256(pdf_bytes).hexdigest()))
        except Exception as ex:
            errors.append({"period": r["period"], "mail_id": r["id"], "error": str(ex)[:200]})
        if i % 25 == 0:
            print("  downloaded %d/%d" % (i, len(targets)), flush=True)
    return manifest, errors


CURRENT_FOLDER = ["INBOX"]
args_force = False


def import_local(src, out):
    pdf_dir = out / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    manifest, errors = [], []
    files = sorted([p for p in Path(src).rglob("*") if p.suffix.lower() == ".pdf"])
    for p in files:
        per = period_of(p.name) or period_of(str(p.parent))
        if not per:
            errors.append({"file": p.name, "error": "cannot infer YYYY-MM period from filename"})
            continue
        b = p.read_bytes()
        dest = pdf_dir / (per + ".pdf")
        dest.write_bytes(b)
        manifest.append(dict(period=per, mail_id="", subject="(local import)",
                             original=p.name, bytes=len(b),
                             sha256=hashlib.sha256(b).hexdigest()))
    return manifest, errors


def main():
    global args_force
    ap = argparse.ArgumentParser(description="Read-only credit-card statement collector")
    ap.add_argument("--out", default="./audit_out", help="output directory")
    ap.add_argument("--provider", default="qq", choices=list(PROVIDERS) + ["custom"])
    ap.add_argument("--host", default="")
    ap.add_argument("--port", type=int, default=993)
    ap.add_argument("--user-env", default="MAIL_USER")
    ap.add_argument("--token-env", default="MAIL_TOKEN")
    ap.add_argument("--folder", action="append", help="specific folder(s); repeatable")
    ap.add_argument("--folders", default="all", choices=["all", "inbox"])
    ap.add_argument("--sender", action="append", default=[],
                    help="required substring in From (repeatable, OR)")
    ap.add_argument("--subject", action="append", default=[],
                    help="required substring in Subject (repeatable, OR)")
    ap.add_argument("--since", default="", help="only messages received on/after YYYY-MM-DD")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--from-dir", default="", help="import PDFs from a local folder instead of IMAP")
    ap.add_argument("--force", action="store_true", help="re-download even if a PDF is cached")
    ap.add_argument("--scan-only", action="store_true", help="scan headers only, do not download")
    args = ap.parse_args()
    args_force = args.force
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if args.from_dir:
        manifest, errors = import_local(args.from_dir, out)
        rows, excluded, dup = [], [], []
    else:
        M, rows = scan_mail(args)
        try:
            targets, excluded, dup = classify(rows, args)
            print("Matched statements: %d | bank-like but excluded: %d | duplicate periods: %d"
                  % (len(targets), len(excluded), len(dup)), flush=True)
            dump_csv(out / "mail_index.csv",
                     ["folder", "id", "date", "from", "subject", "reason"],
                     [{**r, "reason": ""} for r in rows])
            isolation = {
                "total_messages_scanned": len(rows),
                "selected_statements": len(targets),
                "bank_like_excluded": len(excluded),
                "duplicate_periods": len(dup),
                "excluded_samples": [{k: r.get(k, "") for k in ("date", "from", "subject", "reason")}
                                     for r in excluded[:60]],
                "duplicate_samples": [{k: r.get(k, "") for k in ("date", "from", "subject", "period")}
                                      for r in dup[:30]],
                "sender_filter": args.sender,
                "subject_filter": args.subject,
                "received_since": args.since or "(all)",
                "note": "Verify this table before analysis. Statements from a different bank "
                        "must never enter the ledger.",
            }
            write_json(out / "isolation_report.json", isolation)
            if args.scan_only:
                for r in targets[:8]:
                    print("  ", r["date"][:10], r["period"], r["subject"][:70])
                print("  ...")
                for r in targets[-8:]:
                    print("  ", r["date"][:10], r["period"], r["subject"][:70])
                return
            manifest, errors = download(M, targets, out)
        finally:
            try:
                M.logout()
            except Exception:
                pass

    dump_csv(out / "manifest.csv",
             ["period", "mail_id", "subject", "original", "bytes", "sha256"],
             sorted(manifest, key=lambda r: r["period"]))
    write_json(out / "fetch_report.json", {
        "pdf_files": len(manifest),
        "errors": errors,
        "period_first": min((r["period"] for r in manifest), default=""),
        "period_last": max((r["period"] for r in manifest), default=""),
        "isolation": "see isolation_report.json" if rows else "local import",
    })
    print("Done: %d PDFs, %d errors -> %s" % (len(manifest), len(errors), out / "pdf"), flush=True)
    if errors:
        print("First errors:", errors[:5], flush=True)


if __name__ == "__main__":
    main()
