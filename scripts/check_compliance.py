#!/usr/bin/env python3
"""Step 5 — Rule engine: turn the closed ledger into graded findings and letter questions.

Every finding carries: status (hit / clean / need_evidence), the concrete facts,
the amount at stake, the rule/law reference, and an evidence-strength label.
`need_evidence` is deliberately common: a bank statement alone cannot prove
most compliance breaches, and a credible letter asks the bank to produce its
own records rather than asserting what it cannot see.

Also emits the DO-NOT-CITE list so that debunked internet claims never reach
the letter. That list has prevented real letters from being dismissed.

Usage: python3 check_compliance.py --out ./audit_out [--no-pdf-scan]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import D, ZERO, dump_csv, f, money, read_csv, read_json, write_json  # noqa: E402

RULES_PATH = Path(__file__).parent.parent / "assets" / "rules.json"

REQUESTS = {
    "post_2017_late_fee": "请提供上述扣费的业务依据、收费文件编号、公示记录与本人确认记录；如无法提供，请书面说明并退还。",
    "penalty_agreement": "请提供与本人就违约金另行签署的协议原件或电子签约可回溯记录、生效日期、告知方式与本人确认凭证。",
    "fee_in_interest_base": "请提供逐日计息明细：每日计息本金、利率、计息起止日、复利计算方式、还款冲抵顺序，并明确年费/违约金/取现手续费/货币兑换费是否曾计入计息基数。",
    "duplicate_annual_fee": "请提供卡种、历年适用年费标准、减免/积分抵扣条件、每一笔年费的扣收依据，以及历次年费返还的业务类型、审批单号与触发原因。",
    "value_added_fee": "请提供每项服务的名称、价格、公示文件、开通渠道、本人主动申请或确认的记录（含时间、IP/设备、录音编号）。",
    "fee_naming_after_transition": "请说明过渡期届满后分期资金成本的命名、年化利率展示口径，并出示整改完成时间与依据。",
    "auto_instalment": "请逐笔提供：本人事前独立申请记录、单独签订的分期合同、以具有法律效力方式确认的凭证、办理页面截图与当年年化利率披露页；并说明账单中「已绑定」声明的业务来源与生效依据。",
    "annualized_disclosure": "请提供历年信用卡协议、领用合约、分期办理页面、官网资费公示的历史版本，以及其中载明年化利率的页面与本人的确认记录。",
    "rate_negotiation": "请提供 2021-01-01 之后与本卡透支利率「自主协商确定」的完整记录，包括协商时间、渠道、内容与本人确认凭证；并说明现行日利率/年化利率及其生效依据。",
    "implied_high_rate": "请提供上述期间的逐日计息明细，说明是否采用全额罚息、是否对已还部分继续计息、复利基数构成，并复核计息结果。",
    "duplicate_transactions": "请提供上述交易的签购单/调单影像、商户编号、终端号、授权码与清算流水，说明同日同额是否为重复入账。",
    "blank_adjustment": "请提供调账的业务类型、发起部门、审批单号、原始凭证与入账依据。",
    "limit_changes": "请逐次说明额度调整属于固定额度还是临时额度、触发原因、审批记录、生效与到期日，以及向本人通知的时间、渠道与内容。",
    "points_redemption": "请提供历年积分兑换年费规则全文及版本变更记录、本卡各年度可用积分与到期积分明细、本人兑换申请记录、未兑换年度的提醒记录，并说明是否存在自动全额抵扣义务。",
    "excessive_total_cost": "请按年度列示本卡综合息费年化水平，并说明在息费显著偏高时是否履行过提示与适当性义务。",
    "original_contract": "请提供本人办卡当年的申请表原件影像、领用合约、本人抄录签名页、费用信息表、申请资料编号与销毁/归档登记，以及历年资费公示版本和查询渠道告知记录。",
    "invoice": "请按本函所列分项，为历年已收取的年费、透支利息、分期利息/手续费、取现手续费等开具合规发票（个人抬头），并说明开票主体、税目与所属期；如部分无法开具，请逐项书面说明法律依据。",
    "statute_split": "请书面确认已收到本异议函并完整归档，随附投诉编号；后续答复请逐条编号对应，不得以「系统无记录」或「超过查询期限」概括答复。",
}


def scan_pdfs(pdf_dir):
    """Full-text evidence: auto-instalment declarations and annualised-rate disclosures."""
    res = {"pdfs": 0, "annualized_mentions": 0, "auto_declaration_periods": [],
           "auto_first": "", "auto_last": "", "auto_sample": ""}
    if not pdf_dir.exists():
        return res
    try:
        import pymupdf
    except ImportError:
        return res
    for fp in sorted(pdf_dir.glob("*.pdf")):
        try:
            d = pymupdf.open(fp)
            t = "\n".join(p.get_text() for p in d)
            d.close()
        except Exception:
            continue
        res["pdfs"] += 1
        res["annualized_mentions"] += t.count("年化")
        if "自动办理" in t or "自动分期" in t or "自动样样行" in t:
            per = fp.stem
            res["auto_declaration_periods"].append(per)
            if not res["auto_first"]:
                res["auto_first"] = per
                i = t.find("自动")
                res["auto_sample"] = " ".join(t[max(0, i - 70):i + 210].split())[:260]
            res["auto_last"] = per
    return res


def run_detectors(out, analysis, do_pdf_scan):
    txns = read_csv(out / "transactions.csv")
    stmts = sorted(read_csv(out / "statements.csv"), key=lambda r: r["period"])
    base = [t for t in txns if t["currency"] == "人民币"]
    A = analysis["totals"]
    pdf = scan_pdfs(out / "pdf") if do_pdf_scan else {
        "pdfs": 0, "annualized_mentions": 0, "auto_declaration_periods": [],
        "auto_first": "", "auto_last": "", "auto_sample": ""}
    R = {}

    def put(key, status, fact, amount="", strength="—", extra=None):
        R[key] = {"status": status, "fact": fact, "amount": amount,
                  "strength": strength, "extra": extra or {}}

    # C01
    late = [t for t in base if t["period"] >= "2017-01"
            and (t["category"] in ("滞纳金", "超限费")
                 or "滞纳金" in t["raw_line"] or "超限费" in t["raw_line"])]
    amt = sum((D(t["post_amount"]) for t in late), ZERO)
    put("post_2017_late_fee", "hit" if late else "clean",
        ("检出 %d 笔，合计 %s 元" % (len(late), money(amt))) if late
        else "2017-01 之后未检出滞纳金或超限费",
        f(amt), "强" if late else "—", {"rows": len(late)})

    # C02
    pen = [t for t in base if t["category"] == "违约金"]
    put("penalty_agreement", "need_evidence" if pen else "clean",
        ("检出 %d 笔违约金，合计 %s 元；账单无法证明另签协议" % (len(pen), money(sum((D(t['post_amount']) for t in pen), ZERO))))
        if pen else "未检出违约金", f(sum((D(t["post_amount"]) for t in pen), ZERO)),
        "中" if pen else "—")

    # C03
    interest = D(A["interest_total"])
    put("fee_in_interest_base", "need_evidence" if interest else "clean",
        "累计利息 %s 元；是否已将年费等服务费用计入计息基数，账单无法判定" % money(interest)
        if interest else "无利息", f(interest), "中" if interest else "—")

    # C04
    yf = defaultdict(int)
    for t in base:
        if t["category"] == "年费" and D(t["post_amount"]) > 0:
            yf[t["period"][:4]] += 1
    dups = {y: n for y, n in yf.items() if n > 1}
    put("duplicate_annual_fee", "hit" if dups else "need_evidence",
        ("同一年度多次扣收年费：%s" % dups) if dups
        else "共扣收 %d 次年费（%s 元），返还 %s 元，净额 %s 元；须核对卡种减免与积分抵扣规则"
             % (sum(yf.values()), money(A["annual_fee_charged"]),
                money(A["annual_fee_refunded"]), money(A["annual_fee_net"])),
        A["annual_fee_net"], "强" if dups else "中", {"years": sorted(yf)})

    # C05
    vaf = [t for t in base if t["category"] == "增值服务费"]
    put("value_added_fee", "hit" if vaf else "clean",
        ("检出 %d 笔，合计 %s 元" % (len(vaf), money(sum((D(t['post_amount']) for t in vaf), ZERO))))
        if vaf else "未检出未授权的短信/保险/权益类增值服务费",
        f(sum((D(t["post_amount"]) for t in vaf), ZERO)), "强" if vaf else "—")

    # C06
    post_fee = [t for t in base if t["period"] >= "2024-07" and t["category"] == "分期手续费"]
    put("fee_naming_after_transition", "hit" if post_fee else "need_evidence",
        ("过渡期后检出 %d 笔「手续费」名目的分期成本，合计 %s 元" %
         (len(post_fee), money(sum((D(t['post_amount']) for t in post_fee), ZERO))))
        if post_fee else "2024-07 后未检出以「手续费」名目收取的分期成本；仍须核对办理页面披露",
        f(sum((D(t["post_amount"]) for t in post_fee), ZERO)),
        "强" if post_fee else "中")

    # C07
    auto_txns = [t for t in base if "自动" in t["summary"] and "分期" in t["summary"]]
    auto_amt = sum((D(t["post_amount"]) for t in auto_txns
                    if t["category"] in ("利息", "分期手续费")), ZERO)
    dec = pdf["auto_declaration_periods"]
    fact = "检出 %d 笔自动分期相关交易，息费合计 %s 元" % (len(auto_txns), money(auto_amt))
    if dec:
        fact += "；账单声明出现于 %d 期（%s → %s）" % (len(dec), pdf["auto_first"], pdf["auto_last"])
    put("auto_instalment", "hit" if (auto_txns or dec) else "clean", fact,
        f(auto_amt), "强" if auto_txns else ("中" if dec else "—"),
        {"declaration_periods": len(dec), "sample": pdf["auto_sample"],
         "contracts": len(analysis["installment_contracts"])})

    # C08
    disc = pdf["annualized_mentions"]
    put("annualized_disclosure", "need_evidence",
        "%d 份账单全文中「年化」出现 %d 次（扫描 %d 份 PDF）；账单不是法定展示位置，此处仅作间接证据"
        % (pdf["pdfs"], disc, pdf["pdfs"]),
        f(sum((D(t["post_amount"]) for t in base if t["category"] == "利息"), ZERO)), "中",
        {"annualized_mentions": disc, "pdfs_scanned": pdf["pdfs"]})

    # C09
    put("rate_negotiation", "need_evidence",
        "2021-01-01 起透支利率由双方自主协商确定；账单仅显示扣息结果，未见协商依据",
        A["interest_total"], "中")

    # C10
    diag = analysis["interest_diagnostics"]
    put("implied_high_rate", "hit" if diag["above_0_5_count"] else "need_evidence",
        "%d 个计息期可粗算隐含日利率，其中 %d 期高于 0.5‰/日；需逐日计息明细复核"
        % (diag["count"], diag["above_0_5_count"]),
        "", "中" if diag["above_0_5_count"] else "弱",
        {"rows": diag["rows"][:12]})

    # C11
    groups = defaultdict(list)
    for t in base:
        if t["category"] in ("消费", "分期本金") and D(t["post_amount"]) > 0:
            groups[(t["txn_date"], t["post_amount"], t["summary"][:30])].append(t)
    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    dup_amt = sum((D(t["post_amount"]) for v in dup_groups.values() for t in v[1:]), ZERO)
    put("duplicate_transactions", "need_evidence" if dup_groups else "clean",
        "%d 组同日同额同摘要交易，涉及 %s 元（待调单确认，非认定重复扣款）"
        % (len(dup_groups), money(dup_amt)) if dup_groups else "未检出同日同额同摘要组合",
        f(dup_amt), "中" if dup_groups else "—")

    # C12
    blank = [t for t in base if t["category"] == "其他冲账" and not t["summary"].strip()]
    put("blank_adjustment", "need_evidence" if blank else "clean",
        "%d 笔无摘要冲账，合计 %s 元" %
        (len(blank), money(sum((D(t["post_amount"]) for t in blank), ZERO)))
        if blank else "未检出无摘要冲账",
        f(sum((D(t["post_amount"]) for t in blank), ZERO)), "中" if blank else "—")

    # C13
    changes = []
    prev = None
    for s in stmts:
        cur = s.get("credit_limit", "")
        if cur and cur != prev:
            if prev is not None:
                changes.append({"period": s["period"], "from": prev, "to": cur})
            prev = cur
    put("limit_changes", "need_evidence" if changes else "clean",
        "检出 %d 次额度变动（%s → %s）；须先区分固定额度与临时额度到期恢复"
        % (len(changes), changes[0]["from"] if changes else "—",
           changes[-1]["to"] if changes else "—") if changes else "未检出额度变动",
        "", "中" if changes else "—", {"changes": changes[:20]})

    # C14
    refunds = [t for t in base if t["category"] == "年费" and D(t["post_amount"]) < 0]
    put("points_redemption", "need_evidence",
        "检出 %d 笔年费返还，合计 %s 元；须核对积分兑换规则、历次申请记录与未兑换年度的告知"
        % (len(refunds), money(-sum((D(t["post_amount"]) for t in refunds), ZERO)))
        if refunds else "未检出年费返还；仍须核对积分抵扣年费规则",
        A["annual_fee_net"], "中")

    # C15
    put("excessive_total_cost", "need_evidence",
        "累计息费 %s 元，占净消费 %s%%；此为成本占比而非综合年化，须银行按年列示后方可判断"
        % (money(A["bank_fees_and_interest"]), A["cost_rate_pct"]),
        A["bank_fees_and_interest"], "弱")

    # C16
    put("original_contract", "need_evidence",
        "账期 %s → %s，共 %d 期；原始申请表、领用合约与历版资费公示须由银行提供"
        % (analysis["meta"]["period_first"], analysis["meta"]["period_last"],
           analysis["meta"]["statements"]), "", "强")

    # C17
    put("invoice", "need_evidence",
        "就已收取的年费、利息、分期息费及各项手续费合计 %s 元申请开具发票"
        % money(A["bank_fees_and_interest"]), A["bank_fees_and_interest"], "强")

    # C18
    st = analysis["statute"]
    put("statute_split", "need_evidence",
        "%d 年时效切分点 %s：时效内息费 %s 元，时效外 %s 元（时效外不等于必然不可协商）"
        % (analysis["meta"]["limitation_years"], st["cutoff"],
           money(st["fees_within_limit"]), money(st["fees_outside_limit"])),
        st["fees_within_limit"], "程序性", {"cutoff": st["cutoff"]})

    return R, pdf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./audit_out")
    ap.add_argument("--rules", default=str(RULES_PATH))
    ap.add_argument("--no-pdf-scan", action="store_true")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    analysis = read_json(out / "analysis.json")
    if not analysis:
        sys.exit("Missing analysis.json — run analyze_costs.py first")
    rules = json.loads(Path(args.rules).read_text(encoding="utf-8"))
    R, pdf = run_detectors(out, analysis, not args.no_pdf_scan)

    findings, questions = [], []
    for r in rules["rules"]:
        d = R.get(r["detector"], {"status": "need_evidence", "fact": "—", "amount": "",
                                  "strength": "—", "extra": {}})
        findings.append({
            "id": r["id"], "title": r["title"], "severity": r["severity"],
            "status": d["status"], "fact": d["fact"], "amount": d["amount"],
            "evidence_strength": d["strength"],
            "law": "；".join(r["law"]), "claim": r["claim"], "note": r["note"],
            "extra": json.dumps(d["extra"], ensure_ascii=False)[:500],
        })
        questions.append({
            "id": r["question"], "rule_id": r["id"], "title": r["title"],
            "fact": d["fact"], "law": "；".join(r["law"]),
            "request": REQUESTS.get(r["detector"], "请逐项书面说明并提供相应凭证。"),
            "note": r["note"], "amount": d["amount"],
            "status": d["status"],
        })
    questions.sort(key=lambda q: q["id"])
    for i, q in enumerate(questions, 1):
        q["number"] = "Q%02d" % i
        q["id"] = "Q%02d" % i

    summary = Counter(x["status"] for x in findings)
    write_json(out / "findings.json", {
        "meta": {"rules_version": rules["version"], "verified_as_of": rules["verified_as_of"],
                 "pdfs_scanned": pdf["pdfs"], "pdf_evidence": {k: v for k, v in pdf.items()
                                                               if k != "auto_declaration_periods"}},
        "summary": dict(summary), "findings": findings,
        "questions": questions, "do_not_cite": rules["do_not_cite"],
    })
    dump_csv(out / "findings.csv",
             ["id", "title", "severity", "status", "fact", "amount",
              "evidence_strength", "law", "claim", "note"],
             [{k: x[k] for k in ("id", "title", "severity", "status", "fact", "amount",
                                 "evidence_strength", "law", "claim", "note")}
              for x in findings])
    write_json(out / "questions.json", questions)
    print("Findings: %s | questions: %d | PDFs scanned: %d"
          % (dict(summary), len(questions), pdf["pdfs"]))
    for x in findings:
        if x["status"] == "hit":
            print("  HIT %-4s %s" % (x["id"], x["fact"][:100]))
    print("DO-NOT-CITE list: %d entries (must be honoured in the letter)"
          % len(rules["do_not_cite"]))


if __name__ == "__main__":
    main()
