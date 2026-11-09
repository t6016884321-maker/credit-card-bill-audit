---
name: credit-card-bill-audit
description: 信用卡历史账单深度核查与用卡成本分析。当用户要求查看/统计/分析信用卡账单、核对银行收费、计算累计年费与利息、检查乱扣费或违规收费、追查自动分期与积分抵年费、索取银行发票、生成发给银行的书面异议/质询/维权函、出具消费分析 PDF 报告时使用。支持从邮箱（IMAP 授权码）只读取数或本地 PDF 导入，经金额闭合闸门校验后生成两份 PDF。关键词：信用卡账单、对账单、年费、循环利息、分期手续费、自动分期、违约金、滞纳金、全额罚息、退息、发票、12378、消费投诉、credit card statement audit, annual fee, revolving interest, billing dispute。This skill should be used when a cardholder wants a full-period, verifiable audit of credit-card fees and interest and two ready-to-use PDF deliverables.
agent_created: true
---

# 信用卡历史账单深度核查

## 这个 skill 解决什么

多数持卡人从未完整看过十几年的账单：不知道累计付了多少年费、多少利息、多少分期手续费，
不知道「每期手续费」对应的实际年化是多少，不知道自动分期是不是自己同意过，
也不知道积分是否本可抵扣年费。等到想问银行，账单只显示结果、不显示依据。

把全过程固化为可复现流水线：**取数 → 结构化 → 金额闭合闸门 → 多口径核算 →
合规规则比对 → 两份 PDF**。核心原则：

1. **不预设银行违规，也不替银行留情面。** 每条质疑标注证据强度；「已检出」「未检出」「需索证」严格分开。
2. **任何一个数字都必须能回算。** 逐笔明细保留 PDF 页码与行号，全部金额用 Decimal 保留原始两位小数。
3. **闸门未通过，绝不输出金额。** 账不闭合时下游全部阻断，避免给出看似精确实则错误的结论。
4. **不得引用被证伪或已废止的说法。** 见 `references/regulations.md` 与 `assets/rules.json` 的 `do_not_cite`。
5. **凭据只从环境变量读，绝不落盘；取数全程只读。**

## 何时使用

- 用户拿到银行补寄的历史账单（邮件附件 / 本地 PDF），要求「算清楚一共花了多少」。
- 用户质疑年费、利息、分期、违约金、增值服务费、额度调整、积分抵扣。
- 用户要向银行逐条质询、索要原始材料或发票、准备投诉材料。
- 用户要一份可打印的用卡分析总结 + 一份可直接发送的维权函。

## 交给用户的三步准备（先说清，再动手）

1. **要求银行补寄查询期间的完整账单到邮箱。** 话术模板见 `references/mail_setup.md`；
   银行通常在 24 小时内完成。提醒用户同时核对「收取选项／邮件同步范围」覆盖全部历史邮件。
2. **提供邮箱的「授权码」（不是登录密码）。** 说明用途、只读范围与撤销方式；
   若用户不愿提供，改用「手动导出全部账单到本地文件夹」路径（`--from-dir`），二者产出一致。
3. **确认两份交付物**：①期间用卡情况分析与总结；②可发给银行的书面异议／索证／权利主张函。

## 工作流

所有命令在 `scripts/` 下执行；结果统一写入 `--out` 指定的工作目录（默认 `./audit_out`）。
优先使用一键编排 `run_pipeline.py`；需要调参时分步执行。

### 步骤 0：确认环境与依赖

```bash
python3 -c "import pymupdf; print('pymupdf ok')"
python3 scripts/render_pdf.py --check
```

需要 `pymupdf`（PDF 文字坐标提取）与任一 PDF 后端（WeasyPrint / Chrome / wkhtmltopdf）。
若 PDF 是扫描件（无文本层），先做 OCR，否则无法按坐标还原表格。

### 步骤 1：只读取数

```bash
MAIL_USER=you@example.com MAIL_TOKEN=xxxxxxxxxxxxxxxx \
python3 scripts/run_pipeline.py --out ./audit_out \
  --provider qq --sender 银行域名 --subject 对账单关键词 \
  --since 2026-11-09 --bank 发卡银行名称
```

- 环境变量名可用 `--user-env` / `--token-env` 调整。**绝不把凭据写成命令行参数或写入文件。**
- IMAP 以 `readonly=True` 打开，全部使用 `BODY.PEEK[]`，不标记已读、不移动、不删除。
- 用 `--sender` 与 `--subject` 双重过滤，并生成 `isolation_report.json` 列出被排除的银行类邮件。
  **不同银行的账单绝不能混算**，出具报告前必须复核该表。
- 若用户手动导出：`--from-dir /path/to/pdfs`，完全不接触邮箱凭据。
- 下载清单 `manifest.csv` 为每个 PDF 记录 SHA256。

### 步骤 2：探测账单版式（换银行时必做）

```bash
python3 scripts/profile_statements.py --out ./audit_out
```

输出 `profile_suggestion.json`（页数、是否加密/扫描件、金额列 x 坐标聚类、日期格式、区块关键词）。
据此复制 `assets/profiles/` 里的一份配置改出新 profile。**至少用 3 个不同年份的账单校准。**
`cgb_classic_platinum.json` 是经 192 期验证的白金卡账单范例，坐标不可直接套用到别家银行。

### 步骤 3：解析 + 闸门校验（最关键）

```bash
python3 scripts/parse_statements.py   --out ./audit_out --profile cgb_classic_platinum
python3 scripts/validate_ledger.py    --out ./audit_out      # 失败时 exit 2，禁止继续
```

`validate_ledger.py` 执行 V1–V7：期次覆盖、逐期勾稽式、逐笔合计对勾稽表、
跨期余额衔接、全期累计闭合、分类合计、非货币行/未知币种污染。
只有 `validation.json` 中 `gate=pass` 才允许进入报告阶段。

解析阶段已固化四个真实踩过的坑，**改动解析器前先读 `references/statement_profiles.md`**：

- 「积分」行的金额长得像钱，混入会让累计余额差数万元；
- 外币行与本币行并列，必须按最右侧货币列分离，只把本币计入总额；
- 「无欠款」通常对应溢缴存款（负余额），记成 0 会让前后两期各差一笔；
- 「分期冲帐」是分期成立时冲回原消费，不是提前结清、不是退款。

### 步骤 4：多口径核算与合规比对

```bash
python3 scripts/analyze_costs.py    --out ./audit_out --as-of 2026-11-09
python3 scripts/check_compliance.py --out ./audit_out
```

- 五个口径严格分开：毛消费 / 净消费 / 银行息费 / 经济总支出 / 实际还款，另列期末未还余额。
- 输出年度表、费用分项、年费逐笔、利息名目、隐含日利率、分期合同 IRR、
  3 年时效内外切分、用卡行为指标。
- `assets/rules.json` 的 C01–C18 规则生成分级 findings 与 Q01–Q18 质询条目。
  账单本身通常**无法证明**大多数合规问题，因此 `need_evidence` 是常态，
  正确做法是要求银行出示自己掌握的记录，而不是凭空断言违规。

### 步骤 5：生成两份 PDF

```bash
python3 scripts/build_reports.py --out ./audit_out --bank 你的发卡银行 --name 信用卡
```

产出位于 `./audit_out/deliverables/`：

| 文件 | 用途 |
|---|---|
| `1_…消费分析与总结.pdf` | 用户自用：来源隔离、闭合校验、五口径总量、年度双图、消费结构、息费构成、分期 IRR、用卡行为、问题清单、**明明白白用卡改进清单**、时效预期、可核验附件目录 |
| `2_致…书面异议索证及权利主张函.pdf` | 可直接发银行：四合一函件（投诉＋账单异议＋个人信息查阅复制＋发票申请）、逐条编号质询、发票专章、26 项权利清单、A/B/C 三层主张、15 日时限与升级路径、证据目录、签署栏 |

HTML 原件一并保留，供填写姓名、证件号、联系方式后再打印。

### 一键与干跑

```bash
# 完整流程（含取数）
MAIL_USER=... MAIL_TOKEN=... python3 scripts/run_pipeline.py --out ./audit_out --bank XX银行

# 无凭据、无真实账单的合成数据全链路验证
python3 scripts/run_pipeline.py --out ./demo_out --dry-run

# 修好 profile 后从第 3 步续跑
python3 scripts/run_pipeline.py --out ./audit_out --from-step 3 --profile my_bank.json
```

## 交付时必须对用户讲清的边界

- **强证据可直接主张退还的金额**，只取 `findings` 中 `status=hit` 且证据强度为「强」的条目；
  没有就如实写 0 元，不把协商空间抬成法定必退。
- **时效**：《民法典》188 条 3 年、195 条书面异议中断。时效外金额不等于必然不可协商，
  但不能写成法院必然支持。
- **不主张全额退息**；不找收费「退息代办」中介；不提供卡片密码验证码；
  不伪造材料；不要求删除真实征信记录。
- **法规会变**。发出函件前复核 `references/regulations.md` 所列现行有效版本与官方法源链接。
  本 skill 输出是数据分析与自查材料，**不构成法律意见**。
- 完成后提醒用户**立即撤销邮箱授权码**、修改曾在对话中出现过的密码；
  用 `grep -rIl` 扫描工作目录确认无凭据残留。

## 资源索引

| 路径 | 内容 |
|---|---|
| `references/mail_setup.md` | 各邮箱授权码获取、银行补寄账单话术、只读取数与隐私规范 |
| `references/regulations.md` | 法规时间轴、条文号、官方链接、**已废止/误传纠正清单** |
| `references/audit_rules.md` | C01–C18 检查规则、阈值、证据强度分级、常见误报 |
| `references/statement_profiles.md` | 账单模板适配指南与四个真实解析陷阱 |
| `references/rights_and_remedies.md` | 发票、26 项权利、投诉时限、举证责任、升级路径 |
| `references/report_spec.md` | 两份报告的章节规范与可核验性要求 |
| `assets/rules.json` | 规则表 + `do_not_cite` 禁用依据清单 |
| `assets/rights.json` | 权利清单、升级渠道、禁止事项 |
| `assets/profiles/*.json` | 已验证模板配置与通用启发式配置 |
| `assets/report.css` | 报告打印版式 |
| `scripts/*.py` | 上述六步 + 公共模块 + PDF 渲染 + 合成数据 + 一键编排 |
| `examples/README.md` | 脱敏演示与预期输出说明 |
