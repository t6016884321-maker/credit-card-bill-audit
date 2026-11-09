# 脱敏演示 / Synthetic demo

本目录**不含任何真实账单、真实交易或个人信息**。仓库里所有可运行的示例都来自
`scripts/make_sample_data.py` 现场生成的合成数据。

## 跑一遍完整流水线（推荐先做这个）

```bash
python3 scripts/run_pipeline.py --out ./demo_out --dry-run
```

它会自动：

1. 生成 24 个连续账期（默认 2024-01 → 2025-12）、约 100 笔合成交易；
2. 跑 `validate_ledger.py` 的七项闸门校验；
3. 跑多口径核算与 C01–C18 合规比对；
4. 生成两份 PDF + 对应 HTML 到 `./demo_out/deliverables/`。

预期输出（数值会随参数变化）：

```
[OK] V1  Period coverage ...
[OK] V2  Per-statement reconciliation closes ...
[OK] V3  Transaction rows reconcile to the statement totals ...
[OK] V4  Cross-period balances link up ...
[OK] V5  Full-period ledger closure ...
[OK] V6  Category totals equal transaction total ...
[OK] V7  No non-monetary rows / unknown currencies ...
GATE = PASS
...
Findings: {'clean': ..., 'need_evidence': ..., 'hit': ...}
OK  [chrome] 1_...消费分析与总结.pdf
OK  [chrome] 2_致...书面异议索证及权利主张函.pdf
```

## 验证闸门确实会阻断

故意改坏一笔金额，再跑闸门，应看到 `GATE = FAIL` 并以 **exit code 2** 退出：

```bash
cp -r ./demo_out /tmp/ccba_broken
python3 - <<'PY'
import csv
p = "/tmp/ccba_broken/transactions.csv"
rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
rows[0]["post_amount"] = "999999.99"
w = csv.DictWriter(open(p, "w", newline="", encoding="utf-8-sig"),
                   fieldnames=list(rows[0].keys()))
w.writeheader(); w.writerows(rows)
PY
python3 scripts/validate_ledger.py --out /tmp/ccba_broken; echo "exit=$?"
```

此时 `analyze_costs.py` 与 `build_reports.py` 都会拒绝运行——这正是设计意图：
**账不闭合，绝不输出任何金额。**

## 生成的文件

| 文件 | 说明 |
|---|---|
| `transactions.csv` | 逐笔明细（含页码、行号、原始行文本） |
| `statements.csv` | 每期账户信息与勾稽式 |
| `summary_all.csv` | 逐期勾稽行（含币种） |
| `manifest.csv` | 原件清单与 SHA256 |
| `validation.json` / `balance_walk.csv` | 闸门结果与逐期余额推导 |
| `analysis.json` / `annual_summary.csv` / `fee_detail.csv` | 核算结果 |
| `findings.json` / `findings.csv` / `questions.json` | 规则命中与质询条目 |
| `deliverables/` | 两份 PDF + HTML 原件 |

## 想贡献真实案例？

**请不要**把真实账单、交易明细、卡号或邮箱提交到仓库。
可以贡献的是：脱敏后的**版式配置**（`assets/profiles/*.json`）、
解析坑位说明、法规核对结果。详见 [CONTRIBUTING.md](../CONTRIBUTING.md)。
