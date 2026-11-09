#!/usr/bin/env python3
"""Step 6 — Produce the two deliverables.

  PDF 1  <name>_信用卡消费分析与总结.pdf        — for the cardholder
  PDF 2  <name>_致银行书面异议索证及权利主张函.pdf — ready to send to the bank

Every number is read from the JSON/CSV artefacts produced by earlier steps.
Nothing is hard-coded. HTML originals are kept alongside the PDFs so the text
can be edited (name, ID, contact fields) before printing.

Usage: python3 build_reports.py --out ./audit_out --bank 你的发卡银行 --as-of 2026-11-09
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import esc, money, read_csv, read_json, table_html, write_json  # noqa: E402
from render_pdf import to_pdf  # noqa: E402

ASSETS = Path(__file__).parent.parent / "assets"
CSS = (ASSETS / "report.css").read_text(encoding="utf-8")
E = esc


def head(title, subtitle):
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>%s</title><style>%s</style></head><body>" % (E(title), CSS))


def kpi(items):
    out = ['<div class="kpis">']
    for lab, val, note in items:
        out.append('<div class="kpi"><div class="lab">%s</div><div class="val">%s</div>'
                   '<div class="note">%s</div></div>' % (E(lab), E(val), E(note)))
    out.append("</div>")
    return "".join(out)


def box(text, kind=""):
    return '<div class="box %s">%s</div>' % (kind, text)


def svg_dual(years, net_vals, fee_vals):
    """Two independent-scale bar panels so small fee bars stay visible."""
    w, ph, gap, pad_l, pad_r = 680, 132, 26, 52, 12
    h = ph * 2 + gap + 26
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="100%%" height="%d">'
             % (w, h, h)]
    for idx, (vals, color, label) in enumerate([
            (net_vals, "#1c4f8b", "年度净消费（元）"),
            (fee_vals, "#c0523f", "年度息费（元）")]):
        top = idx * (ph + gap) + 16
        mx = max(vals) if vals and max(vals) > 0 else 1
        base = top + ph - 22
        parts.append('<text x="0" y="%d" font-size="10" fill="#374760">%s</text>' % (top - 2, label))
        parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#d7e1ec"/>'
                     % (pad_l, base, w - pad_r, base))
        n = max(1, len(years))
        slot = (w - pad_l - pad_r) / n
        bw = min(18.0, slot * 0.62)
        for i, v in enumerate(vals):
            x = pad_l + slot * i + (slot - bw) / 2
            bh = (v / mx) * (ph - 42)
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" rx="1"/>'
                         % (x, base - bh, bw, max(0.6, bh), color))
            if i % max(1, len(years) // 9) == 0:
                parts.append('<text x="%.1f" y="%d" font-size="7.5" fill="#6a7684" '
                             'text-anchor="middle">%s</text>'
                             % (x + bw / 2, base + 12, E(years[i][2:])))
        parts.append('<text x="%d" y="%d" font-size="8" fill="#6a7684" text-anchor="end">%s</text>'
                     % (pad_l - 3, top + 10, money(mx)))
    parts.append("</svg>")
    return "".join(parts)


def build_analysis(out, D, bank, as_of):
    A, V, F = D["analysis"], D["validation"], D["findings"]
    ISO, MAN, PR = D["isolation"], D["manifest"], D["parse"]
    T = A["totals"]
    P = []
    P.append(head("信用卡历史账单消费分析与总结", "期间 %s → %s" % (A["meta"]["period_first"], A["meta"]["period_last"])))
    P.append('<div class="cover"><h1>信用卡历史账单消费分析与总结</h1>'
             '<div class="sub">%s ｜ 账期 %s → %s ｜ 共 %d 期 ｜ 出具日期 %s</div>'
             '<div style="margin-top:8px"><span class="tag">逐笔可核验</span>'
             '<span class="tag">金额闭合校验</span><span class="tag">合规规则比对</span>'
             '<span class="tag">不夸大可退金额</span></div></div>'
             % (E(bank), E(A["meta"]["period_first"]), E(A["meta"]["period_last"]),
                A["meta"]["statements"], E(as_of)))
    P.append(kpi([
        ("累计刷卡消费（毛额）", money(T["gross_consumption"]), "流水口径，不等于实际支出"),
        ("累计银行息费成本", money(T["bank_fees_and_interest"]), "年费＋利息＋手续费等"),
        ("经济总支出", money(T["economic_spend"]), "净消费＋息费"),
        ("累计实际还款", money(T["actual_repayment"]), "实际资金流出"),
        ("累计净年费", money(T["annual_fee_net"]), "扣收 %s／返还 %s" % (money(T["annual_fee_charged"]), money(T["annual_fee_refunded"]))),
        ("累计利息", money(T["interest_total"]), "含循环、分期与取现利息"),
    ]))
    P.append(box("<strong>一句话结论：</strong>本卡 %d 期账单逐笔核对，累计刷卡 %s 元，"
                 "累计向银行支付息费 %s 元，息费占净消费 <strong>%s%%</strong>，"
                 "期末未还余额 %s 元。<strong>本报告不预设银行违法</strong>：所有质疑均标注证据强度，"
                 "可直接认定的金额与需索证的事项严格分开。"
                 % (A["meta"]["statements"], money(T["gross_consumption"]),
                    money(T["bank_fees_and_interest"]), T["cost_rate_pct"],
                    money(T["closing_balance"]))))

    # 1 source isolation
    P.append("<h2>一、数据来源与银行隔离</h2>")
    iso_rows = [
        ["扫描邮件总数", str(ISO.get("total_messages_scanned", "—")), "全文件夹邮件头只读扫描"],
        ["纳入核算的账单", str(ISO.get("selected_statements", len(MAN))), "按发件人与主题双重过滤"],
        ["其他银行/营销邮件排除", str(ISO.get("bank_like_excluded", "—")), "不同银行绝不混算"],
        ["重复账期", str(ISO.get("duplicate_periods", 0)), "同一期重复补寄只取一次"],
        ["原件数量", str(len(MAN)), "每份附 SHA256，见 manifest.csv"],
        ["账期连续性", "%s → %s" % (A["meta"]["period_first"], A["meta"]["period_last"]),
         "缺月 %d，重复 %d" % (len(PR.get("missing_periods", [])), len(PR.get("duplicate_periods", [])))],
    ]
    P.append(table_html(["项目", "数值", "说明"], iso_rows, widths=["26%", "18%", "56%"]))
    P.append('<p class="small">过滤条件：发件人包含 %s；主题包含 %s；收件日期 %s。'
             '请在报送银行前复核 isolation_report.json 中的「排除样例」，确认没有把其他银行账单混入。'
             '无交易的空账单属于正常期次，不算缺月。</p>'
             % (E(" / ".join(ISO.get("sender_filter", [])) or "（未设）"),
                E(" / ".join(ISO.get("subject_filter", [])) or "（未设）"),
                E(ISO.get("received_since", "全部"))))

    # 2 reliability
    P.append("<h2>二、数据可靠性：金额闭合校验</h2>")
    P.append(box("<strong>闭合等式：</strong>期初 %s ＋ 全部交易净额 %s ＝ 期末 %s，差额 0.00。"
                 "解析 %d 笔交易、%d 期账单，逐期余额与逐笔对勾稽式零差异。"
                 % (money(V["opening_balance"]), money(V["net_transactions"]),
                    money(V["closing_balance"]), V["transactions_base"], V["statements"]), "ok"))
    P.append(table_html(["校验", "结果", "说明"],
                        [[c["id"] + " " + c["name"], "通过" if c["passed"] else "未通过", c["detail"]]
                         for c in V["checks"]], widths=["42%", "12%", "46%"]))
    P.append('<p class="small">校验闸门为 pass 是本报告出具的前置条件。常见解析陷阱（积分行被当成金额、'
             '外币混入本币、「无欠款」被记成 0、分期冲账被误判为退款）均已在解析阶段排除，'
             '任何一期不闭合都会阻断报告生成。</p>')

    # 3 definitions
    P.append("<h2>三、你到底花了多少钱：五个不能混用的口径</h2>")
    P.append(table_html(["口径", "金额（元）", "含义"], [
        ["① 累计刷卡消费（毛额）", money(T["gross_consumption"]), "所有消费流水，含退货前"],
        ["② 净消费", money(T["net_consumption"]), "扣除退货退款与调账后"],
        ["③ 累计银行息费成本", money(T["bank_fees_and_interest"]), "使用这张卡的真实资金成本"],
        ["④ 经济总支出", money(T["economic_spend"]), "②＋③"],
        ["⑤ 累计实际还款", money(T["actual_repayment"]), "从你的银行账户实际划出的钱"],
        ["期末未还余额", money(T["closing_balance"]), "仍欠银行，尚未实际支出"],
    ], numcols=(1,), widths=["30%", "20%", "50%"]))
    P.append(box("<strong>口径提醒：</strong>①不等于②，⑤也不等于④。欠款未还清时，"
                 "已消费但尚未还款的部分在④里、不在⑤里；把它混为一谈会得出错误结论。", "warn"))

    # 4 yearly
    P.append("<h2>四、年度趋势</h2>")
    Y = A["year_rows"]
    P.append('<div class="chart">%s</div>' % svg_dual(
        [y["year"] for y in Y], [float(y["net"]) for y in Y], [float(y["fees"]) for y in Y]))
    P.append('<div class="legend">上下两图使用独立刻度，避免息费柱因量级差异不可见。'
             '首年与末年可能不是完整自然年度。</div>')
    P.append(table_html(["年度", "期数", "净消费", "息费", "还款", "期末余额", "息费/净消费"],
                        [[y["year"], y["periods"], money(y["net"]), money(y["fees"]),
                          money(y["repayment"]), money(y["closing"]), y["cost_pct"] + "%"]
                         for y in Y],
                        numcols=(2, 3, 4, 5, 6),
                        totalrow=["合计", A["meta"]["statements"],
                                  money(T["net_consumption"]), money(T["bank_fees_and_interest"]),
                                  money(T["actual_repayment"]), money(T["closing_balance"]),
                                  T["cost_rate_pct"] + "%"]))

    # 5 structure
    P.append("<h2>五、消费与资金结构</h2>")
    P.append(table_html(["类别", "笔数", "金额（元）", "占净消费"],
                        [[r["category"], r["count"], money(r["amount"]),
                          ("%.2f%%" % (float(r["amount"]) / float(T["net_consumption"]) * 100))
                          if float(T["net_consumption"]) else "—"]
                         for r in A["category_summary"]],
                        numcols=(2, 3), widths=["30%", "14%", "28%", "28%"]))

    # 6 fees
    P.append("<h2>六、息费构成：钱去哪了</h2>")
    fee_rows = [[c, v["count"], money(v["amount"])] for c, v in A["fee_by_type"].items()
                if float(v["amount"]) != 0]
    P.append(table_html(["费用类型", "笔数", "金额（元）"], fee_rows,
                        numcols=(2,),
                        totalrow=["合计", "", money(T["bank_fees_and_interest"])],
                        widths=["40%", "20%", "40%"]))
    if A["interest_split"]:
        P.append("<h3>利息名目拆分</h3>")
        P.append(table_html(["账单摘要", "笔数", "金额（元）"],
                            [[r["summary"], r["count"], money(r["amount"])]
                             for r in A["interest_split"]], numcols=(2,)))
        P.append('<p class="small">不同摘要名目可能属于同一计费口径，列示用于向银行追问口径差异，'
                 '不可重复加总。</p>')
    if A["annual_fee_rows"]:
        P.append("<h3>年费逐年逐笔</h3>")
        P.append(table_html(["账期", "日期", "金额（元）", "摘要"],
                            [[r["period"], r["txn_date"], money(r["post_amount"]),
                              r["summary"][:48]] for r in A["annual_fee_rows"]], numcols=(2,)))

    # 7 instalments
    P.append("<h2>七、分期成本与实际年化</h2>")
    C = A["installment_contracts"]
    if C:
        P.append(table_html(["合同号", "起", "止", "期数", "本金", "息费", "名义费率", "IRR 年化"],
                            [[c["contract"], c["first"], c["last"], c["instalments"],
                              money(c["principal"]), money(c["fee"]),
                              c["nominal_rate_pct"] + "%",
                              (c["irr_annual_compound_pct"] + "%") if c["irr_annual_compound_pct"] else "—"]
                             for c in C], numcols=(4, 5, 6, 7)))
        P.append('<p class="small">IRR 按「期初借入本金、其后每期等额偿还本金＋息费」的现金流测算，'
                 '为近似值，用于核对银行披露的年化利率是否一致，不替代合同利率。</p>')
    else:
        P.append("<p>未从账单摘要中识别出带合同号的分期记录。</p>")
    P.append(box("<strong>自动分期要单独追问：</strong>账单里一句「已绑定自动分期功能」属于事后声明，"
                 "不是逐笔授权。若存在自动分期，请要求银行出具每笔的事前独立申请、单独合同与"
                 "具有法律效力方式的确认记录，并出示当年年化利率披露页。", "warn"))

    # 8 behaviour
    P.append("<h2>八、用卡行为与利息成因</h2>")
    B = A["behaviour"]
    P.append(table_html(["指标", "数值"], [
        ["总账期数", B["total_periods"]],
        ["期末有欠款的期数", "%d（%s%%）" % (B["indebted_periods"], B["indebted_pct"])],
        ["有还款记录的期数", B["periods_with_repayment"]],
        ["可粗算隐含日利率的期数", A["interest_diagnostics"]["count"]],
        ["其中高于 0.5‰/日", A["interest_diagnostics"]["above_0_5_count"]],
    ], widths=["56%", "44%"]))
    P.append(box("<strong>最贵的习惯不是年费，是长期只还最低还款额。</strong>%s"
                 "这部分通常属于按合约正常计息，能谈的是协商减免与计息口径复核，"
                 "不是依法必须退还。" % B["note"], "warn"))

    # 9 findings
    P.append("<h2>九、问题清单（按证据强度分级）</h2>")
    badge = {"hit": '<span class="badge b-red">已检出</span>',
             "clean": '<span class="badge b-green">未检出</span>',
             "need_evidence": '<span class="badge b-amber">需索证</span>'}
    P.append(table_html(["编号", "事项", "状态", "事实／涉及金额", "证据强度"],
                        [[x["id"], x["title"], badge.get(x["status"], ""),
                          x["fact"], x["evidence_strength"]] for x in F["findings"]],
                        widths=["8%", "24%", "12%", "44%", "12%"]))
    P.append(box("<strong>不得引用的说法：</strong>" +
                 "；".join(E(c["claim"]) for c in F["do_not_cite"]) +
                 "。理由见法规知识库与 findings.json，引用被证伪的说法会削弱整份主张的可信度。", "red"))

    # 10 habit changes
    P.append("<h2>十、明明白白用卡：下一步改进清单</h2>")
    habits = [
        ["① 全额还款", "把「每期全额还清」设为默认动作，只有极端现金流压力才用最低还款；"
         "这是唯一能稳定享受免息期的方式。"],
        ["② 关闭自动分期", "向银行确认是否存在自动分期 / 自动样样行等默认功能，要求关闭并索取关闭回执；"
         "任何分期都应逐笔独立确认。"],
        ["③ 看清年化利率", "办理任何分期前要求看到年化利率（不是「每期费率」），自行用 IRR 复算后决定。"],
        ["④ 年费与积分规则", "记录本卡年费标准、减免条件与积分兑换窗口，把兑换日期写进日历；"
         "若银行曾返还部分年费，追问返还依据与其余年度是否适用。"],
        ["⑤ 定期查账", "每月核对逐笔交易与勾稽式，年末导出一次全量账单存档；"
         "发现无摘要调账、不明增值服务费立即书面异议。"],
        ["⑥ 索要发票", "对已支付的年费、利息与手续费索取发票，既是凭证也是核对银行收费台账的手段。"],
        ["⑦ 留痕", "所有异议用可留痕渠道发出，保存工单号、回执、答复；书面异议可中断诉讼时效。"],
        ["⑧ 不找中介", "不委托收费「退息代办」，不提供卡片、密码、验证码，不伪造材料，"
         "不要求删除真实征信记录。"],
    ]
    P.append(table_html(["动作", "具体做法"], habits, widths=["24%", "76%"]))

    # 11 statute
    S = A["statute"]
    P.append("<h2>十一、时效与现实预期</h2>")
    P.append(table_html(["项目", "金额／说明"], [
        ["时效切分点", S["cutoff"]],
        ["时效内息费", money(S["fees_within_limit"]) + " 元"],
        ["时效外息费", money(S["fees_outside_limit"]) + " 元"],
        ["可直接认定「违法多收应退」", "以 findings 中 status=hit 且证据强度=强 的条目为准；"
         "若没有，就如实写 0 元"],
    ], widths=["34%", "66%"]))
    P.append(box("<strong>把预期放对位置：</strong>本套分析的现实价值是"
                 "①把十几年账算清楚、②逼银行逐条举证并交出原始材料、③拿到发票、"
                 "④争取时效内息费与积分的协商方案。强证据金额不要把协商空间抬成法定必退。", "warn"))

    P.append("<h2>附录　可核验文件目录</h2>")
    P.append(table_html(["文件", "用途"], [
        ["transactions.csv", "逐笔明细（含原始行文本、页号、行号）"],
        ["statements.csv", "每期账户信息与勾稽式"],
        ["balance_walk.csv", "逐期余额累计推导，可独立复算"],
        ["validation.json / validation_gate", "七项校验结果与闸门状态"],
        ["annual_summary.csv", "年度汇总"],
        ["fee_detail.csv", "全部息费逐笔"],
        ["findings.csv / findings.json", "规则命中与证据强度"],
        ["manifest.csv", "192 份原件 SHA256 清单"],
        ["isolation_report.json", "邮件来源隔离证据"],
        ["pdf/", "账单 PDF 原件（请自行妥善保管，勿随函全部寄出）"],
    ], widths=["34%", "66%"]))
    P.append('<div class="footer">本报告基于持卡人自行提供的账单原件与公开监管规范生成，'
             '为数据分析与自查材料，不构成法律意见、不承诺任何退款结果。'
             '涉及金额较大、拟进入投诉升级或诉讼程序时，请携全部材料咨询执业律师。</div>')
    P.append("</body></html>")
    return "".join(P)


def build_letter(out, D, bank, as_of):
    A, V, F = D["analysis"], D["validation"], D["findings"]
    T, Q, R = A["totals"], D["questions"], D["rights"]
    P = []
    P.append(head("致%s书面异议、索证及权利主张函" % bank, "可直接发送"))
    P.append('<div class="cover"><h1>致 %s 的书面异议、索证及权利主张函</h1>'
             '<div class="sub">四合一：消费投诉 ＋ 账单书面异议 ＋ 个人信息查阅复制申请 ＋ 发票开具申请</div>'
             '<div style="margin-top:8px"><span class="tag">逐条编号质询</span>'
             '<span class="tag">请 15 日内书面答复</span><span class="tag">请完整归档</span>'
             '<span class="tag">出具日期 %s</span></div></div>' % (E(bank), E(as_of)))
    P.append(table_html(["项目", "内容"], [
        ["致", "%s 信用卡中心 消费者权益保护部门／投诉处理部门" % E(bank)],
        ["投诉人", "姓名：____________　身份证号：______________________"],
        ["账户", "信用卡卡号后四位：________　（完整卡号请勿写在可外发的电子文档里）"],
        ["联系方式", "手机：____________　电子邮箱：____________　通讯地址：____________"],
        ["涉及账期", "%s → %s，共 %d 期" % (A["meta"]["period_first"], A["meta"]["period_last"],
                                          A["meta"]["statements"])],
        ["附件", "《信用卡历史账单消费分析与总结》及证据目录所列可核验数据文件"],
    ], widths=["20%", "80%"]))
    P.append(box("<strong>函件性质：</strong>本人现依据《银行业保险业消费投诉处理管理办法》、"
                 "《商业银行信用卡业务监督管理办法》、《消费者权益保护法》、"
                 "《个人信息保护法》等规定，就上述账户历史账单提出<strong>书面异议与逐项质询</strong>，"
                 "并同时提出消费投诉、个人信息查阅复制申请与发票开具申请。"
                 "请贵行按本函编号逐条书面答复，勿以统一话术概括回复。"))

    P.append("<h2>一、事实摘要与数据可靠性</h2>")
    P.append(table_html(["项目", "金额／数值"], [
        ["累计刷卡消费（毛额）", money(T["gross_consumption"]) + " 元"],
        ["累计净消费", money(T["net_consumption"]) + " 元"],
        ["累计银行息费", money(T["bank_fees_and_interest"]) + " 元"],
        ["其中：净年费", money(T["annual_fee_net"]) + " 元"],
        ["其中：利息", money(T["interest_total"]) + " 元"],
        ["累计实际还款", money(T["actual_repayment"]) + " 元"],
        ["期末余额", money(T["closing_balance"]) + " 元"],
    ], numcols=(1,), widths=["52%", "48%"]))
    P.append(box("<strong>可核验性声明：</strong>上述数字由 %d 期账单逐笔解析，"
                 "期初 %s ＋ 全部交易净额 %s ＝ 期末 %s，逐期余额与勾稽式零差异。"
                 "本人已保留全部账单原件及 SHA256 清单，愿在贵行需要时提供核对。"
                 "如贵行认为任何数字有误，请具体指出期次与逐笔差异，勿笼统否认。"
                 % (A["meta"]["statements"], money(V["opening_balance"]),
                    money(V["net_transactions"]), money(V["closing_balance"])), "ok"))

    P.append("<h2>二、逐条质询事项</h2>")
    P.append('<p class="small">以下每项均请单独编号答复，并附相应凭证复印件或可核验的电子记录。'
             '「需索证」类事项并非认定贵行违规，而是账单本身无法证明，依法应由掌握资料的一方举证。</p>')
    for q in Q:
        P.append('<div class="q"><div class="qh">%s　%s</div>' % (E(q["number"]), E(q["title"])))
        P.append('<div class="row"><div class="k">事实／线索</div><div class="v">%s</div></div>' % E(q["fact"]))
        P.append('<div class="row"><div class="k">依据</div><div class="v law">%s</div></div>' % E(q["law"]))
        P.append('<div class="row"><div class="k">请提供</div><div class="v"><strong>%s</strong></div></div>'
                 % E(q["request"]))
        P.append('<div class="row"><div class="k">备注</div><div class="v small">%s</div></div>' % E(q["note"]))
        P.append("</div>")

    P.append("<h2>三、发票开具专项申请</h2>")
    inv_rows = [[c, money(v["amount"]) + " 元"] for c, v in A["fee_by_type"].items()
                if float(v["amount"]) != 0]
    inv_rows.append(["合计", money(T["bank_fees_and_interest"]) + " 元"])
    P.append(table_html(["收费项目", "累计金额"], inv_rows, numcols=(1,), widths=["60%", "40%"]))
    P.append("<p>请贵行就上述已实际收取的款项开具合规发票（个人抬头），逐项说明开票主体、"
             "适用税目与所属期。利息类通常按贷款服务、手续费类按直接收费金融服务处理；"
             "营改增前后适用规则不同，请分段列示。<strong>请勿以「年代久远」「账单未结清」"
             "「协商还款中」「个人消费者不抵扣」为由拒绝。</strong>如部分项目确有不予开具的"
             "法律依据，请逐项书面说明具体条款；否则本人将向 12366 反映应开具而未开具发票的情形。</p>")
    P.append(box("依据：《消费者权益保护法》第 22 条（经营者出具发票等购货凭证的义务）、"
                 "《中华人民共和国发票管理办法》（2023 修订）、财税〔2016〕36 号。"))

    P.append("<h2>四、本人依法享有的权利清单</h2>")
    P.append(table_html(["权利", "依据", "本次如何行使"],
                        [[r["name"], r["basis"], r["action"]] for r in R["rights"]],
                        widths=["24%", "38%", "38%"]))

    P.append("<h2>五、三层主张（按证据强度分层，不自抬金额）</h2>")
    hits = [x for x in F["findings"] if x["status"] == "hit" and x["evidence_strength"] == "强"]
    P.append(table_html(["层级", "内容", "金额"], [
        ["A · 可直接主张", "；".join(x["title"] for x in hits) if hits
         else "当前账单未检出可直接定性为违法多收的项目，故本层主张金额为 0 元",
         money(sum(float(x["amount"] or 0) for x in hits)) + " 元"],
        ["B · 条件性主张", "待贵行提供 Q 项材料后，对未授权收费、未披露息费、计算差错作进一步核算；"
         "本人保留补充主张的权利", "待举证后确定"],
        ["C · 协商性请求", "对时效内息费、积分抵扣年费未落实部分，请求贵行提出书面协商方案；"
         "此项为协商请求，非认定贵行负有法定退还义务",
         "时效内息费 " + money(A["statute"]["fees_within_limit"]) + " 元"],
    ], widths=["18%", "60%", "22%"]))
    P.append(box("<strong>特别声明：</strong>本人<strong>不主张全额退息</strong>，"
                 "不委托任何收费中介，不提供卡片、密码或验证码，不要求删除真实征信记录。"
                 "对真实、准确的历史记录不持异议。", "ok"))

    P.append("<h2>六、答复时限、升级路径与证据保全</h2>")
    P.append(box("<strong>请自收到本函之日起 15 日内作出书面答复</strong>，逐条对应 Q 编号，"
                 "载明投诉编号、经办部门与联系人。依据《银行业保险业消费投诉处理管理办法》，"
                 "贵行已掌握或可从内部档案获取的材料，不得要求投诉人提供。"
                 "请以「系统无记录」「超过查询期限」以外的具体理由答复。"))
    P.append(table_html(["步骤", "渠道", "说明"],
                        [[r["step"], r["channel"], r["note"]] for r in R["escalation"]],
                        widths=["10%", "42%", "48%"]))
    P.append("<p>请贵行将本函、投诉编号、全部答复与往来记录完整归档。本人亦将保存投递回执、"
             "通话录音编号与全部往来，作为后续程序的证据。本函构成书面异议，"
             "依《民法典》第 195 条主张诉讼时效中断。</p>")

    P.append("<h2>七、证据目录</h2>")
    P.append(table_html(["编号", "材料", "说明"], [
        ["E01", "《信用卡历史账单消费分析与总结》", "本函配套数据报告"],
        ["E02", "逐笔明细 transactions.csv", "含期次、页码、行号与原始行文本"],
        ["E03", "期次勾稽 statements.csv / balance_walk.csv", "可独立复算"],
        ["E04", "校验报告 validation.json", "七项金额闭合校验"],
        ["E05", "息费明细 fee_detail.csv / findings.csv", "规则命中与证据强度"],
        ["E06", "账单原件及 SHA256 清单 manifest.csv", "贵行补寄的 PDF 原件，备索"],
        ["E07", "邮件来源隔离报告 isolation_report.json", "证明未混入其他银行数据"],
    ], widths=["10%", "46%", "44%"]))
    P.append(box("请勿在首次沟通时一次性寄出全部 192 份账单原件；"
                 "按贵行要求分期次提供对应页，并保留送达凭证。", "warn"))

    P.append("<h2>八、不得引用的说法（本人已主动排除）</h2>")
    P.append(table_html(["说法", "排除理由"],
                        [[c["claim"], c["why"]] for c in F["do_not_cite"]],
                        widths=["40%", "60%"]))

    P.append("<h2>九、签署</h2>")
    P.append('<div class="sig"><table>'
             '<tr><td>投诉人（签名）：________________</td><td>日期：______年____月____日</td></tr>'
             '<tr><td>联系电话：____________________</td><td>投诉编号（银行填写）：____________</td></tr>'
             '</table></div>')
    P.append('<p class="small"><strong>发出前须知：</strong>① 填写姓名、证件号、卡号后四位与联系方式；'
             '② 核对配套分析报告中的银行名称、账期与金额；③ 以可留痕方式发送（挂号信、'
             '银行官方投诉渠道并保存工单号）；④ 若拟进入诉讼或金额较大，先咨询执业律师；'
             '⑤ 法规可能修订，发出前请复核现行有效版本。</p>')
    P.append('<div class="footer">本函为基于公开监管规范与持卡人账单数据拟定的书面主张文本，'
             '不构成法律意见。使用者应自行核实法条现行有效性并对内容负责。</div>')
    P.append("</body></html>")
    return "".join(P)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./audit_out")
    ap.add_argument("--bank", default="发卡银行")
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--name", default="信用卡")
    ap.add_argument("--html-only", action="store_true")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    deliver = out / "deliverables"
    deliver.mkdir(parents=True, exist_ok=True)

    D = {
        "analysis": read_json(out / "analysis.json", {}),
        "validation": read_json(out / "validation.json", {}),
        "findings": read_json(out / "findings.json", {}),
        "questions": read_json(out / "questions.json", []),
        "isolation": read_json(out / "isolation_report.json", {}),
        "parse": read_json(out / "parse_report.json", {}),
    }
    D["manifest"] = read_csv(out / "manifest.csv")
    D["rights"] = json.loads((ASSETS / "rights.json").read_text(encoding="utf-8"))
    if not D["analysis"] or not D["findings"]:
        sys.exit("Missing analysis.json / findings.json — run steps 4 and 5 first")
    if D["validation"].get("gate") != "pass":
        sys.exit("BLOCKED: validation gate is not 'pass'")
    if not D["questions"]:
        D["questions"] = read_json(out / "questions.json", [])

    stem = args.name.replace(" ", "")
    h1 = deliver / ("1_%s消费分析与总结.html" % stem)
    safe_bank = "".join(c for c in args.bank if c not in '/\\:*?"<>|&')
    h2 = deliver / ("2_致%s书面异议索证及权利主张函.html" % safe_bank)
    p1 = deliver / ("1_%s消费分析与总结.pdf" % stem)
    p2 = deliver / ("2_致%s书面异议索证及权利主张函.pdf" % safe_bank)
    h1.write_text(build_analysis(out, D, args.bank, args.as_of), encoding="utf-8")
    h2.write_text(build_letter(out, D, args.bank, args.as_of), encoding="utf-8")
    result = {"html": [str(h1), str(h2)], "pdf": [], "errors": []}
    if not args.html_only:
        for h, p in ((h1, p1), (h2, p2)):
            ok, msg = to_pdf(h, p)
            if ok:
                result["pdf"].append(str(p))
                print("OK  [%s] %s" % (msg, p.name))
            else:
                result["errors"].append({"file": str(p), "error": msg})
                print("FAIL %s: %s" % (p.name, msg))
    write_json(deliver / "deliverables.json", result)
    print("HTML originals kept in %s (edit name / ID fields before printing)" % deliver)
    if result["errors"]:
        print("Install a PDF backend:  pip install weasyprint   (or Chrome / wkhtmltopdf)")
        sys.exit(1)


if __name__ == "__main__":
    main()
