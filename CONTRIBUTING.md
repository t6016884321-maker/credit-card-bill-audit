# 贡献指南 / Contributing

最欢迎的贡献是**新银行的账单解析配置**和**法规更新**。PR 前请先读
[SECURITY.md](SECURITY.md)：**任何真实账单、交易明细、卡号、邮箱或凭据都不得提交。**

## 1. 新增一家银行的解析 profile

每家银行 PDF 的列坐标、区块关键词、日期格式都不同。流程：

```bash
# 用你自己的（脱敏）账单，或自行构造的合成 PDF
python3 scripts/fetch_bills.py --from-dir ./my_pdfs --out ./audit_out
python3 scripts/profile_statements.py --out ./audit_out
cat ./audit_out/profile_suggestion.json

cp assets/profiles/generic.json assets/profiles/<bank>_<card>.json
# 编辑 date_re / markers / columns / summary
python3 scripts/parse_statements.py --out ./audit_out --profile <bank>_<card> --limit 3
python3 scripts/validate_ledger.py --out ./audit_out
```

提交前必须满足：

- [ ] 至少用**首期、中期、末期** 3 个不同年份的账单验证过；
- [ ] `validate_ledger.py` 七项检查全绿（`gate=pass`）；
- [ ] `transactions.csv` 前 10 行与 PDF 原件逐行人工比对一致；
- [ ] 配置文件里 `notes` 写清该模板的特殊坑（积分行、外币列、溢缴款等）；
- [ ] 不含任何真实卡号、姓名、金额或文件路径；
- [ ] 在 README 的「支持哪些银行」表格里补一行（注明验证期数）。

详细字段说明见 [references/statement_profiles.md](references/statement_profiles.md)。

## 2. 更新法规与规则

- 修改 `references/regulations.md` 时，必须附**官方来源链接 + 核对日期 + 生效/废止状态**。
- 发现新法条或旧法条被废止 → 同步更新 `assets/rules.json` 的 `rules[].law`
  和 `do_not_cite`。
- 新增检查规则 → 同时更新：
  1. `assets/rules.json`（新 C 编号、severity、law、question、note）；
  2. `scripts/check_compliance.py`（`run_detectors` 里实现 detector，写进 `R`）；
  3. `REQUESTS` 字典（银行应提供什么）；
  4. `references/audit_rules.md`（判定依据与常见误报）。
- **宁可多标 `need_evidence`，也不要把账单无法证明的事写成 `hit`。**

## 3. 改进报告

- 所有数字必须从 JSON/CSV 实时读取，**禁止在模板里硬编码金额或年份**。
- 新增章节同步更新 `references/report_spec.md`。
- 改动版式后用 `python3 scripts/run_pipeline.py --out ./demo_out --dry-run` 重跑，
  并检查：无空白页、无浏览器页眉、无中文乱码、无未替换占位符。

## 4. 提交前自检

```bash
python3 -m py_compile scripts/*.py
python3 scripts/run_pipeline.py --out /tmp/ccba_check --dry-run
python3 /path/to/skill-creator/scripts/quick_validate.py .
git status --short          # 确认没有 audit_out/、*.pdf、*.eml、*.csv
```

## 5. 提交规范

- Commit message：`feat: add <bank> statement profile` / `fix: drop points rows in parser` /
  `docs: update 2026 regulation references`。
- 一个 PR 只做一件事。
- 中文或英文描述均可，但代码注释、配置键名、CLI 参数用英文。

## 6. 行为准则

不接受以下内容：帮助伪造材料、规避正常合同义务、删除真实征信记录、
批量代客投诉、收集他人账单数据、绕过邮箱授权机制。本项目只服务**持卡人核查自己的账单**。
