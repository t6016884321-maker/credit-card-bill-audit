# 安全与隐私 / Security & Privacy

## 一句话原则

**凭据不落盘、取数只读取、数据不出本机、用完即撤销。**

## 1. 凭据处理

| 规则 | 实现 |
|---|---|
| 只从环境变量读 | `MAIL_USER` / `MAIL_TOKEN`，可用 `--user-env` / `--token-env` 改名 |
| 不写命令行参数 | 命令行参数会进入 shell history、进程列表与 CI 日志 |
| 不写文件 | 脚本不把邮箱地址、密码、授权码写入任何 CSV / JSON / 日志 / 记忆 |
| 不写进仓库 | `.gitignore` 排除 `.env*`、运行产物与所有账单文件 |
| 用完撤销 | 在邮箱设置里关闭 IMAP 服务或重新生成授权码 |

正确用法：

```bash
MAIL_USER=you@example.com MAIL_TOKEN=xxxxxxxxxxxxxxxx \
python3 scripts/run_pipeline.py --out ./audit_out
```

错误用法（**不要这样做**）：

```bash
python3 scripts/fetch_bills.py --token xxxxxxxx        # 本工具不支持，也不应该支持
echo "MAIL_TOKEN=xxxx" >> .env && git add .env          # 凭据进入版本库
```

如果授权码或登录密码曾出现在对话、终端或截图里，请**立即修改密码并撤销授权码**。

## 2. 只读取数保证

`fetch_bills.py` 的实现约束：

- `M.select(folder, readonly=True)` —— 只读打开；
- `M.fetch(id, "(BODY.PEEK[])")` —— `PEEK` 不会设置 `\Seen`；
- 不调用 `store` / `copy` / `expunge` / `append`，不标记已读、不移动、不删除、不新增邮件；
- 下载的 `.eml` 与 PDF 只写到本地 `--out` 目录。

## 3. 数据边界

- **所有计算在本机完成**，不调用任何上传接口、不发送遥测、不连第三方分析服务。
- 输出目录 `audit_out/` 含**真实账单与交易明细**，属于个人金融信息：
  - 不要提交到 Git；
  - 不要整体打包发给银行（函件里只提供对方要求的对应页，并保留送达凭证）；
  - 不要上传到公共网盘或在线文档。
- `mail_index.csv` 含发件人与主题，`manifest.csv` 含邮件主题，同属个人数据。
- 生成的函件**不预填完整卡号、身份证号**；这些字段留空由用户手写。

## 4. 发布 / 提交前自检

```bash
# 1. 凭据残留（把 <CODE> 换成实际值，注意别把真实值写进命令历史文件）
grep -rIl -e '<AUTH_CODE>' -e '<PASSWORD>' . || echo "no credential residue"

# 2. 不应出现在仓库里的文件类型
git status --short
find . -type f \( -name '*.eml' -o -name '*.pdf' -o -name 'transactions.csv' \) -print

# 3. 确认 gitignore 生效
git check-ignore -v audit_out/ 2>/dev/null || echo "WARNING: audit_out is not ignored"
```

## 5. 报告准确性同样是安全问题

- 金额闭合闸门（`validate_ledger.py`）是硬性阻断：**账不闭合就不出报告**。
- 函件自动附上「不得引用的说法」清单，避免引用已废止法规或征求意见稿条款。
- 对银行有利的事实必须一并呈现；不夸大、不陷害，是可信度也是自我保护。

## 6. 报告漏洞 / Reporting a vulnerability

若发现脚本会写入凭据、修改邮件、或把个人数据发送到外部，请**不要**在公开 issue 里贴出
真实账单或凭据。请先脱敏，再提交 issue 描述复现步骤；涉及敏感信息可私信维护者。

## 7. 免责

本工具是数据分析与自查材料，不构成法律意见，不提供代理维权，与任何发卡银行无关联。
使用者自行负责所发送内容与后续沟通。
