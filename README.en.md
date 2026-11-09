# Credit Card Bill Audit

[English](README.en.md) · [简体中文](README.md) · [MIT](LICENSE) · [Security](SECURITY.md)

A **free, open-source, fully local** WorkBuddy skill that audits years of
Chinese credit-card statements and produces **two ready-to-use PDFs**.

> Scope: the bundled regulatory references, letter templates and generated
> reports are in **Simplified Chinese** and target **Mainland China** regulations.
> The data pipeline itself is bank-agnostic.

---

## Have you ever asked these?

- Have you ever actually read the fee lines on your credit-card statement?
- Do you know the **total cost** of that card over ten-plus years?
- Can you tell whether every fee the bank charged was justified — and do you
  have the evidence to ask?

Most cardholders only look at "total amount due". Banks never aggregate your
lifetime annual fees, revolving interest, instalment costs, or the points that
could have offset those fees. Statements show results, not the basis for them.

**This skill turns years of statements into a verifiable ledger, so you can see
what you really paid, challenge what needs evidence, and fix the habits that
actually cost money.**

---

## What it does

| Capability | Detail |
|---|---|
| Six separated totals | Gross spend, net spend, bank fees & interest, economic spend, actual repayments, closing balance — never conflated |
| Complete fee breakdown | Annual fees (incl. refunds), revolving / instalment / cash interest, instalment fees, late fees, penalties, value-added service fees — by year, by category, by transaction |
| Real annualised cost | Converts "0.xx% per period" into an **IRR-based annual rate** |
| 18 compliance checks | C01–C18 with explicit evidence grading, plus a built-in **do-not-cite** list of debunked / repealed legal claims |
| Four parser traps handled | Points rows that look like money, foreign-currency rows mixed with CNY, "no balance due" actually meaning an overpayment, instalment reversals mistaken for refunds |
| **Validation gate** | Seven independent checks; if the ledger does not close, **no report is generated** |
| Two PDF deliverables | An analysis report for you, and a numbered dispute / evidence-request / rights letter for the bank |
| Habit change | Eight concrete actions: pay in full, disable auto-instalments, read the APR, track points, reconcile monthly, request invoices, keep records, avoid "refund agents" |

## The two deliverables

**1 · Spending Analysis & Summary (for you)**
Source isolation → closure checks → six totals → dual-scale yearly charts →
spending structure → fee composition → instalment IRR → repayment behaviour →
graded findings → **"Spend with your eyes open" action list** → limitation-period
expectations → verifiable appendix.

**2 · Written Objection, Evidence Request & Rights Letter (ready to send)**
A four-in-one letter (consumer complaint + billing objection + personal-data
access request + invoice request), **Q01–Q18 numbered questions** with
facts / legal basis / documents requested / notes, an invoice chapter,
a 26-item statutory rights table, a three-tier claim structure (A/B/C),
a 15-day response deadline with a six-step escalation path, an evidence index,
and a signature block.

> The goal is **not** "a full refund of all interest". It is to make the bank
> produce its records, hand over original application materials and daily
> interest calculations, issue invoices, and open a negotiation on
> in-limitation fees. When there is no strong evidence, the letter says **0**.
> Overstating a claim destroys credibility.

## Three steps to prepare

1. **Ask the bank to email complete statements** for the period you want.
   Usually delivered within **24 hours**, one PDF per month.
   [Template wording](references/mail_setup.md).
2. **Provide a mailbox authorization code / app password** (not the login
   password). The skill fetches read-only over IMAP. **Alternatively**, export
   the PDFs manually into a folder and use `--from-dir` — no credentials at all.
3. **Receive the two PDFs.** Fill in your name, ID and contact details before
   sending the letter.

## Quick start

```bash
git clone https://github.com/t6016884321-maker/credit-card-bill-audit.git
cd credit-card-bill-audit
python3 -m pip install pymupdf weasyprint
python3 scripts/render_pdf.py --check

# Dry run on synthetic data: no mailbox, no credentials, no real statements
python3 scripts/run_pipeline.py --out ./demo_out --dry-run

# Full run
MAIL_USER=you@example.com MAIL_TOKEN=your_app_password \
python3 scripts/run_pipeline.py --out ./audit_out \
  --provider qq --sender your-bank-domain --subject statement \
  --since 2026-11-09 --bank "Bank Name"

# Offline / manual export
python3 scripts/run_pipeline.py --out ./audit_out \
  --from-dir ~/Downloads/statements --bank "Bank Name"
```

Outputs land in `./audit_out/deliverables/` (two PDFs + editable HTML originals)
plus a dozen verifiable CSV/JSON artefacts in `./audit_out/`.

For a new bank, calibrate the PDF layout first:

```bash
python3 scripts/profile_statements.py --out ./audit_out
python3 scripts/parse_statements.py --out ./audit_out --profile generic --limit 3
python3 scripts/validate_ledger.py --out ./audit_out
```

See [references/statement_profiles.md](references/statement_profiles.md).

## Pipeline

| Step | Script | Key constraint |
|---|---|---|
| 1 Fetch | `fetch_bills.py` | `readonly=True` + `BODY.PEEK[]`; never marks read / moves / deletes; isolation report prevents mixing banks |
| 2 Probe | `profile_statements.py` | Text layer / encryption detection, amount-column x clustering, section markers |
| 3 Parse | `parse_statements.py` | Coordinate-based table reconstruction, `Decimal` with original 2 decimals, points rows dropped, foreign currency separated |
| 4 **Gate** | `validate_ledger.py` | V1–V7; **exit 2 and stop** if the ledger does not close |
| 5 Analyse | `analyze_costs.py`, `check_compliance.py` | Six totals, yearly table, IRR, limitation split, C01–C18 graded findings |
| 6 Report | `build_reports.py`, `render_pdf.py` | Auto-detects WeasyPrint / Chrome / wkhtmltopdf |

## Privacy & security

- Credentials are read **only from environment variables** and never written to
  disk, command-line arguments, logs or memory files.
- IMAP access is strictly read-only.
- **All processing is local.** No statement, transaction or personal data is
  uploaded anywhere.
- Revoke the app password immediately after fetching.
- Review `isolation_report.json` before sending anything, to confirm no other
  bank's statements were mixed in.
- See [SECURITY.md](SECURITY.md).

## FAQ

**Does it call normal interest "illegal overcharging"?**
No. Revolving interest mostly comes from not paying in full. The report states
explicitly that this is normal contractual interest — negotiable, not
automatically refundable. Every finding is graded `hit` / `clean` / `need_evidence`.

**Can I recover fees from ten years ago?**
PRC Civil Code: 3-year ordinary limitation, 20-year maximum. The report splits
in/out of limitation and labels them honestly. Realistic route: written
objection + complaint + negotiation, not a guaranteed court win. Avoid paid
"refund agents".

**Scanned or encrypted PDFs?**
Run OCR first (`ocrmypdf`) for image-only files; ask the bank for a
password-free original for encrypted ones. Never store a PDF password in a profile.

**Which banks are supported?**
Fetching and accounting are bank-agnostic; PDF parsing needs a layout profile.
One profile, validated against **192 statements / nearly 6,000 transactions**
(a Chinese joint-stock bank platinum card), ships as a worked example, plus a
heuristic `generic` profile. Adding a bank usually takes 10–20 minutes —
[contributions welcome](CONTRIBUTING.md).

**Can I send the letter as-is?**
Almost. Fill in personal details, verify bank name / period / amounts, re-check
that the cited regulations are still in force, send through a channel that
leaves a receipt, and keep the complaint number. Consult a qualified lawyer
before litigation or for large amounts.

## Disclaimer

This is a **data-analysis and self-audit tool**, not legal advice. It makes no
promise of any refund, provides no representation service, and is not affiliated
with any card issuer. Regulations change — verify current effective texts on
official regulator websites before sending a formal letter. Users are
responsible for the content they send.

## License

[MIT](LICENSE).
