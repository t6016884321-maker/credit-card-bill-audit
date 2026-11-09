#!/usr/bin/env python3
"""One-command orchestration of the whole audit.

Steps
  1 fetch_bills.py        collect statement PDFs (read-only IMAP or local folder)
  2 profile_statements.py probe PDF layout, write a calibration suggestion
  3 parse_statements.py   build the structured ledger
  4 validate_ledger.py    THE GATE — aborts the pipeline unless the ledger closes
  5 analyze_costs.py      multi-definition cost accounting
  6 check_compliance.py   graded findings + letter questions
  7 build_reports.py      the two PDF deliverables

Credential rules:
  * Export MAIL_USER / MAIL_TOKEN in the shell. Never put them in a file,
    a command-line argument, a notebook, or a chat message transcript.
  * Revoke the mailbox app-password as soon as the fetch completes.

Usage
  # Full run
  MAIL_USER=you@example.com MAIL_TOKEN=xxxxxxxxxxxxxxxx python3 run_pipeline.py \
      --out ./audit_out --provider qq --sender your-bank.com \
      --subject 对账单 --bank 你的发卡银行

  # Offline / manual export
  python3 run_pipeline.py --out ./audit_out --from-dir ~/Downloads/statements --bank 你的发卡银行

  # Dry run on synthetic data (no mailbox, no credentials, no real PDFs)
  python3 run_pipeline.py --out ./demo_out --dry-run

  # Resume after fixing a parsing profile
  python3 run_pipeline.py --out ./audit_out --from-step 3 --profile my_bank.json --bank XX银行
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent.resolve()


def run(script, args, optional=False):
    cmd = [sys.executable, str(HERE / script)] + [str(a) for a in args]
    print("\n" + "=" * 78)
    print("$ %s %s" % (script, " ".join(str(a) for a in args)))
    print("=" * 78, flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        if optional:
            print("[warn] %s exited %d — continuing (non-blocking step)" % (script, r.returncode))
            return False
        print("\n[STOP] %s failed with exit code %d. Pipeline aborted." % (script, r.returncode))
        if script == "validate_ledger.py":
            print("The amount ledger does not close. Fix the parsing profile or obtain "
                  "missing statements. NO report will be produced.")
        sys.exit(r.returncode)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./audit_out")
    ap.add_argument("--bank", default="发卡银行")
    ap.add_argument("--name", default="信用卡")
    ap.add_argument("--provider", default="qq")
    ap.add_argument("--host", default="")
    ap.add_argument("--port", type=int, default=993)
    ap.add_argument("--user-env", default="MAIL_USER")
    ap.add_argument("--token-env", default="MAIL_TOKEN")
    ap.add_argument("--sender", action="append", default=[])
    ap.add_argument("--subject", action="append", default=[])
    ap.add_argument("--since", default="")
    ap.add_argument("--folders", default="all", choices=["all", "inbox"])
    ap.add_argument("--from-dir", default="", help="import PDFs from a local folder")
    ap.add_argument("--profile", default="generic")
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--limit-years", type=int, default=3)
    ap.add_argument("--base-currency", default="人民币")
    ap.add_argument("--from-step", type=int, default=1, choices=range(1, 8))
    ap.add_argument("--only-step", type=int, default=0)
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--no-pdf-scan", action="store_true")
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--allow-missing-periods", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="generate synthetic data and run steps 4-7 without any real statement")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print("DRY RUN — synthetic data only; no mailbox, no credentials, no real statements.")
        run("make_sample_data.py", ["--out", out])
        start = 4
    else:
        start = args.from_step

    def want(n):
        return (args.only_step == 0 and n >= start) or args.only_step == n

    common = ["--out", out]
    if want(1) and not args.skip_fetch and not args.dry_run:
        a = common + ["--provider", args.provider, "--host", args.host,
                      "--port", args.port, "--user-env", args.user_env,
                      "--token-env", args.token_env, "--folders", args.folders]
        for s in args.sender:
            a += ["--sender", s]
        for s in args.subject:
            a += ["--subject", s]
        if args.since:
            a += ["--since", args.since]
        if args.from_dir:
            a += ["--from-dir", args.from_dir]
        run("fetch_bills.py", a)

    if want(2) and not args.dry_run:
        run("profile_statements.py", common, optional=True)

    if want(3) and not args.dry_run:
        run("parse_statements.py", common + ["--profile", args.profile])

    if want(4):
        a = common + ["--base-currency", args.base_currency]
        if args.allow_missing_periods:
            a.append("--allow-missing-periods")
        run("validate_ledger.py", a)

    if want(5):
        run("analyze_costs.py", common + ["--base-currency", args.base_currency,
                                          "--as-of", args.as_of,
                                          "--limit-years", args.limit_years])

    if want(6):
        a = list(common)
        if args.no_pdf_scan or args.dry_run:
            a.append("--no-pdf-scan")
        run("check_compliance.py", a)

    if want(7):
        a = common + ["--bank", args.bank, "--name", args.name, "--as-of", args.as_of]
        if args.html_only:
            a.append("--html-only")
        run("build_reports.py", a)

    print("\n" + "=" * 78)
    print("Pipeline finished. Deliverables: %s" % (out / "deliverables"))
    print("Reminder: revoke the mailbox app-password now if IMAP was used.")
    print("=" * 78)


if __name__ == "__main__":
    main()
