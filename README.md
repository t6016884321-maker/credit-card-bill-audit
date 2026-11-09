# 信用卡历史账单深度核查 · Credit Card Bill Audit

[简体中文](#简体中文) · [English](#english) · [MIT License](LICENSE) · [安全与隐私](SECURITY.md)

一个免费、开源、本地运行的 WorkBuddy Skill：把十几年信用卡账单一次性算清楚，
并生成**两份可直接使用的 PDF**。

---

<a id="简体中文"></a>

## 简体中文

### 先问自己三个问题

> **你是不是从来没有认真看过信用卡账单里的收费明细？**
>
> **你有没有算过，这张卡十几年一共让你付出了多少成本？**
>
> **年费、循环利息、分期手续费、自动分期、积分抵扣、额度调整……
> 银行每一笔扣费都合理吗？你有依据去问吗？**

大多数人只在还款日看一个「本期应还金额」，从不看它怎么来的。
十几年下来，年费扣了多少次、利息复利滚了多少、分期实际年化是多少、
积分本可不可以抵年费——银行不会主动替你汇总，账单也只显示结果、不显示依据。

**这个 skill 帮你一次性搞清楚：明明白白消费，把不清楚的账变成可以逐笔核验的数字，
并从今天开始改掉那些真正烧钱的用卡习惯。**

### 它能做什么

| 能力 | 说明 |
|---|---|
| 一次算清全部成本 | 累计刷卡消费、净消费、银行息费、经济总支出、实际还款、期末未还余额——**六个口径分开列，不混为一谈** |
| 拆开每一分钱 | 年费（含返还）、循环/分期/取现利息、分期手续费、滞纳金、违约金、增值服务费，按年、按类、按笔 |
| 算真实年化 | 把「每期只要 0.xx% 手续费」折算成 IRR 年化，和银行披露口径对照 |
| 严查可疑收费 | 18 条规则 C01–C18：2017 后滞纳金、未授权增值服务、自动分期逐笔授权、过渡期后收费命名、利息计费基数、重复交易、单方调账、额度调整… |
| 揪出解析陷阱 | 积分被当成钱、外币混入本币、「无欠款」其实是溢缴款、分期冲账被误判为退款——这些都曾让总账差数万元 |
| 金额闭合闸门 | 七项独立校验（逐期勾稽式、逐笔对总额、跨期衔接、全期累计…）**不通过就不出报告**，杜绝「看着精确实则算错」 |
| 生成两份 PDF | ①《期间用卡情况分析与总结》；②《致银行书面异议、索证及权利主张函》 |
| 帮你改变习惯 | 报告第十章给出 8 条可执行动作：全额还款、关闭自动分期、看清年化、积分兑换、定期查账、索要发票、全程留痕、远离中介 |

### 两份交付物

**① 消费分析与总结（给你自己看）**
来源隔离 → 闭合校验 → 六口径总量 → 年度趋势双图 → 消费结构 → 息费构成 →
分期 IRR → 用卡行为与利息成因 → 问题清单分级 → **明明白白用卡改进清单** →
时效预期 → 可核验附件目录。

**② 致银行书面异议、索证及权利主张函（可直接发送）**
四合一函件（消费投诉 ＋ 账单书面异议 ＋ 个人信息查阅复制申请 ＋ 发票开具申请）、
**Q01–Q18 逐条编号质询**（每条含事实／法条／请提供的证据／备注）、发票专章、
26 项法定权利清单、A/B/C 三层主张、15 日答复时限与 6 级升级路径、证据目录、签署栏。

> 函件的目标不是「全额退息」。它逼银行逐条举证、交出原始申请材料与计息明细、
> 开具发票，并为时效内息费争取协商方案。**没有强证据就直接写 0 元**，不夸大、不陷害，
> 这样才站得住。

### 三步准备（你需要做的全部）

**第 1 步 · 让银行把账单发到你的邮箱**
打信用卡背面客服电话或在线人工客服，申请补寄「查询期间的全部月度对账单」到预留邮箱。
银行通常 **24 小时内**完成，每月一份 PDF。[照抄话术](references/mail_setup.md#1-让银行补寄完整历史账单)。
> 若用 QQ 邮箱，记得在「设置 → 账号 → 收取选项」把同步范围改成**全部**，
> 否则十几年前的老邮件可能拉不到。

**第 2 步 · 提供邮箱的授权码（不是登录密码）**
AI 会自动、只读地抓取全部账单 PDF，解析并深度分析问题。
[各邮箱授权码获取路径](references/mail_setup.md#2-授权码--邮箱登录密码)。
> **不想给授权码？** 完全可以。把 PDF 手动下载到一个文件夹，用 `--from-dir` 导入，
> 产出完全一致，全程不接触任何邮箱凭据。

**第 3 步 · 拿两份报告**
运行一条命令，得到上面两份 PDF。发出前填写姓名、证件号、联系方式即可。

### 快速开始

```bash
# 1. 下载
git clone https://github.com/t6016884321-maker/credit-card-bill-audit.git
cd credit-card-bill-audit

# 2. 安装依赖（Python 3.9+）
python3 -m pip install pymupdf
python3 -m pip install weasyprint      # 或已安装 Chrome / wkhtmltopdf

# 3. 装成 WorkBuddy 用户级 skill（可选，也可直接命令行用）
./scripts/install.sh

# 4. 先用合成数据干跑一遍，确认环境 OK（不需要邮箱、不需要任何真实账单）
python3 scripts/run_pipeline.py --out ./demo_out --dry-run

# 5. 正式跑（凭据只在环境变量里，不写入任何文件）
MAIL_USER=you@example.com MAIL_TOKEN=你的16位授权码 \
python3 scripts/run_pipeline.py --out ./audit_out \
  --provider qq \
  --sender 你的银行发件域名 \
  --subject 补寄对账单 \
  --since 2026-11-09 \
  --bank 你的发卡银行
```

手动导出路径：

```bash
python3 scripts/run_pipeline.py --out ./audit_out \
  --from-dir ~/Downloads/statements --bank 你的发卡银行
```

产物在 `./audit_out/deliverables/`：两份 PDF + 对应 HTML 原件 + 十余个可核验 CSV/JSON。

> 换银行时先跑 `python3 scripts/profile_statements.py --out ./audit_out` 校准账单版式，
> 详见 [账单模板适配指南](references/statement_profiles.md)。

### 工作原理

| 步骤 | 脚本 | 关键约束 |
|---|---|---|
| 1 取数 | `fetch_bills.py` | IMAP `readonly=True` + `BODY.PEEK[]`；不标已读、不删改；生成隔离报告防不同银行混算 |
| 2 探测 | `profile_statements.py` | 文本层/加密检测、金额列 x 坐标聚类、区块关键词 |
| 3 解析 | `parse_statements.py` | 按文字坐标还原表格；Decimal 保留原始两位小数；剔除积分行、分离外币 |
| 4 **闸门** | `validate_ledger.py` | V1–V7 七项校验；**失败即 exit 2，禁止生成任何金额报告** |
| 5 核算比对 | `analyze_costs.py` / `check_compliance.py` | 六口径、年度表、IRR、时效切分、C01–C18 分级 findings |
| 6 出报告 | `build_reports.py` + `render_pdf.py` | 自动探测 WeasyPrint / Chrome / wkhtmltopdf，生成两份 PDF |

### 安全与隐私

- **凭据只从环境变量读取**，绝不写入文件、命令行参数、日志或记忆；取数全程只读。
- **所有计算在本地完成**，不上传任何账单、交易或个人信息到任何服务器。
- 出具报告前请复核 `isolation_report.json`，确认**没有混入其他银行的账单**。
- 完成后**立即撤销邮箱授权码**；若登录密码曾在对话里出现过，一并修改。
- 详见 [SECURITY.md](SECURITY.md) 与 [邮箱准备规范](references/mail_setup.md)。

### 常见问题

**Q：会不会把「正常利息」也说成乱收费？**
不会。循环利息主要来自长期未全额还款，报告会明确写「按合约正常计息，能谈协商减免、
不是依法必须退」。所有质疑分「已检出 / 未检出 / 需索证」三档。

**Q：十几年前的账还能要回来吗？**
《民法典》普通时效 3 年、最长 20 年。报告按出具日切分时效内外金额并如实标注；
现实路径是书面异议 + 投诉举证 + 协商，不是打官司全赢。**别找收费「退息代办」中介。**

**Q：账单是扫描图片 / 加密 PDF 怎么办？**
扫描件先做 OCR（如 `ocrmypdf`）；加密件请向银行索取无密码原件，不要把密码写进配置。

**Q：支持哪些银行？**
取数与核算逻辑与银行无关；PDF 解析需要对应模板。仓库内置一份经 **192 期、近 6,000 笔交易**
实测验证的某股份制银行白金卡配置作为范例，和一份启发式通用配置。新增银行模板约需 10–20 分钟，
[欢迎提交 PR](CONTRIBUTING.md)。

**Q：可以直接把函件发出去吗？**
可以，但请先：填写个人信息 → 核对报告里的银行名、账期与金额 → 复核法条现行有效版本 →
用可留痕渠道发送并保存工单号。金额较大或拟诉讼前请咨询执业律师。

### 免责声明

本项目是**数据分析与自查工具**，不构成法律意见、不承诺任何退款结果、不提供代理维权服务。
法规会修订或废止，发出正式函件前请通过官方渠道复核现行有效文本。
使用者自行承担发送内容与后续沟通的全部责任。**本项目与任何发卡银行无关联。**

---

<a id="english"></a>

## English

> *A ready-to-use, free and open-source WorkBuddy skill for cardholders worldwide
> to audit Chinese credit-card statements. The bundled regulatory references,
> letter templates and report text are in Simplified Chinese and apply to
> **Mainland China** regulations.*

### Three questions worth asking

- Have you ever actually read the fee lines on your credit-card statement?
- Do you know the **total cost** of owning that card over ten-plus years?
- Can you tell whether every fee the bank charged was justified — and do you
  have the evidence to ask?

Most people only look at "minimum payment due". The bank never aggregates your
lifetime annual fees, revolving interest, instalment costs or points that could
have offset those fees. Statements show results, not the basis for them.

**This skill turns years of statements into a verifiable ledger and two ready-to-use PDFs —
so you can see what you really paid, challenge what needs evidence, and fix the habits
that actually cost money.**

### What it does

- Six clearly separated totals: gross spend, net spend, bank fees & interest,
  economic spend, actual repayments, closing balance.
- Full fee breakdown by year and by transaction: annual fees (and refunds),
  revolving / instalment / cash interest, instalment fees, late fees, penalties,
  value-added service fees.
- Converts "0.xx% per period" into a real **IRR annualised rate**.
- 18 compliance checks (C01–C18) with explicit evidence grading, plus a
  built-in **do-not-cite** list of debunked and repealed legal claims.
- A **seven-check validation gate**: no report is produced unless the ledger closes.
- Two PDFs: an analysis report for you, and a numbered, ready-to-send
  dispute / evidence-request / rights letter for the bank.
- Habits chapter: pay in full, disable auto-instalments, read APR, track points,
  reconcile monthly, request invoices, keep records, avoid "refund agents".

### Three steps to prepare

1. **Ask your bank to email the complete statements** for the period you want
   (usually delivered within 24 hours, one PDF per month).
2. **Provide a mailbox app-password / authorization code** (never the login
   password). The skill fetches read-only via IMAP. Alternatively, **export the
   PDFs manually** to a folder and use `--from-dir` — no credentials involved.
3. **Receive two PDFs**: the spending analysis and the letter to the bank.

### Quick start

```bash
git clone https://github.com/t6016884321-maker/credit-card-bill-audit.git
cd credit-card-bill-audit
python3 -m pip install pymupdf weasyprint
python3 scripts/run_pipeline.py --out ./demo_out --dry-run   # synthetic data, no credentials

MAIL_USER=you@example.com MAIL_TOKEN=your_app_password \
python3 scripts/run_pipeline.py --out ./audit_out \
  --sender your-bank-domain --subject statement --bank "Bank Name"
```

See [SKILL.md](SKILL.md) for the full workflow, and
[references/](references/) for the regulatory index, audit rules, mailbox setup,
statement-profile guide, rights & remedies, and report specification.

### Privacy

Credentials are read from environment variables only and never persisted.
The IMAP session is `readonly` and uses `BODY.PEEK[]`, so no message is marked
read, moved or deleted. All processing is local — no statement data leaves your
machine. Revoke the app-password immediately after the fetch. See [SECURITY.md](SECURITY.md).

### Disclaimer

This is a data-analysis and self-audit tool, **not legal advice**. It does not
promise any refund, does not provide representation, and is not affiliated with
any card issuer. Regulations change — verify the current effective text on
official regulator websites before sending any formal letter. The bundled
templates are in Chinese and target Mainland China regulations.

### License

[MIT](LICENSE) — free for personal and commercial use.
