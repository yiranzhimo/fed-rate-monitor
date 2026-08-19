# Fed Rate Monitor

一个部署在 GitHub Pages 的美联储利率与 FOMC 会议监控仪表盘。GitHub Actions 每小时检查官方数据；只有检测到目标区间、会议日程或关键会议文件发生变化时才发送邮件。

## 数据范围

- 联邦基金目标区间上下限：FRED `DFEDTARU`、`DFEDTARL`
- 实际有效联邦基金利率：FRED `DFF`（原始来源为纽约联储）
- FOMC 会议日期与官方文件：Federal Reserve FOMC Calendar
- 加息、降息及基点数是目标区间中点变化的**推导结果**，并非额外的官方序列

项目不包含市场预测或 CME FedWatch 概率。网页自动化数据可能延迟，不构成投资建议。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python scripts/update_data.py
python3 -m http.server 8000
```

打开 `http://localhost:8000`。抓取失败不会覆盖现有数据；脚本只有在完整取得并验证两类数据后才更新文件。

## 部署到 GitHub Pages

1. 在 GitHub 创建仓库，例如 `fed-rate-monitor`，并推送本目录到 `main`。
2. 工作流会尝试自动启用 GitHub Pages；如果仓库策略禁止自动启用，再进入 **Settings → Pages**，在 **Build and deployment → Source** 选择 **GitHub Actions**。
4. 在 **Actions** 页手动运行一次 `Update FOMC data and deploy`。
5. 可选：在 **Settings → Actions → General** 确认 Workflow permissions 允许读写；工作流本身已声明 `contents: write`。

定时任务在每小时第 17 分钟运行。GitHub Actions 的 cron 可能延迟，因此它用于监控和通知，不适合作为交易级实时信号。

## 邮件通知

工作流使用通用 SMTP。进入 **Settings → Secrets and variables → Actions**，配置：

### Variables

| 名称 | 示例 | 说明 |
|---|---|---|
| `EMAIL_ENABLED` | `true` | 设为 `true` 才发信 |
| `SITE_URL` | `https://你的用户名.github.io/fed-rate-monitor/` | 邮件中的仪表盘链接 |

### Secrets

| 名称 | 示例 | 说明 |
|---|---|---|
| `SMTP_HOST` | `smtp.qq.com` | SMTP 服务器 |
| `SMTP_PORT` | `465` | 可省略，默认 `465`；其他端口使用 STARTTLS |
| `SMTP_USERNAME` | `you@qq.com` | SMTP 登录名 |
| `SMTP_PASSWORD` | `授权码` | 使用 SMTP 授权码，不要使用邮箱登录密码 |
| `EMAIL_FROM` | `you@qq.com` | 可省略，默认等于登录名 |
| `EMAIL_TO` | `you@example.com` | 多个地址用逗号分隔 |

常见配置：

| 邮箱 | Host | Port |
|---|---|---:|
| QQ 邮箱 | `smtp.qq.com` | 465 |
| 163 邮箱 | `smtp.163.com` | 465 |
| Gmail | `smtp.gmail.com` | 587 |

首次运行只建立数据基线，不发送历史更新邮件。后续邮件触发条件：

- 联邦基金目标区间变化；
- 官方 FOMC 会议日期增删或调整；
- 新增政策声明、实施说明、SEP 或会议纪要。

本地预览邮件可先准备一个包含变化事件的 `runtime/change.json`，然后运行：

```bash
python scripts/send_notification.py --dry-run
```

预览会写入被 Git 忽略的 `email_preview.html`，不会连接 SMTP。

## 项目结构

```text
├── index.html / styles.css / app.js   # 静态仪表盘
├── data/                              # 可审计的规范化数据
├── scripts/update_data.py             # 抓取、校验、变更检测
├── scripts/send_notification.py       # SMTP 邮件
├── tests/                              # 解析与变更检测测试
└── .github/workflows/                 # 定时更新及 Pages 部署
```

## 官方来源

- [Federal Reserve FOMC Calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
- [FRED DFEDTARU](https://fred.stlouisfed.org/series/DFEDTARU)
- [FRED DFEDTARL](https://fred.stlouisfed.org/series/DFEDTARL)
- [New York Fed EFFR](https://www.newyorkfed.org/markets/reference-rates/effr)
