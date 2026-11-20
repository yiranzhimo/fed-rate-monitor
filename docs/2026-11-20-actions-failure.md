# GitHub Actions 数据更新失败排查（2026-11-20）

## 时间线与证据

- [GitHub 运行记录] 最近一次成功：2026-11-10 13:33:17 UTC（香港时间 21:33:17），运行 [42825571840](https://github.com/yiranzhimo/fed-rate-monitor/actions/runs/42825571840)。
- [GitHub 运行记录] 本轮连续失败始于 2026-11-10 20:52:35 UTC（香港时间 11 月 11 日 04:52:35）。排查时已有 32 次连续失败。
- [用户提供的运行日志] `Refresh official data` 输出：`update failed: FRED CPIAUCSL series lacks enough history`。
- [官方数据] 2026-11-20 下载的 [FRED CPI/核心 CPI CSV](https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL,CPILFESL) 中，2025-10-01 的两个指数均为空，最新参考月份为 2026-10。
- [本地复现] 将下载的 [FRED 六个宏观序列](https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE,PAYEMS,CPIAUCSL,CPILFESL,PCEPI,PCEPILFE) 输入原版本，可复现完全相同的异常。

## 根因

2026 年 10 月同比需要 2025 年 10 月指数作为分母。该月份缺失，因此 `_year_over_year` 返回 `None`；原来的 `build_macro_dashboard` 把任何同比或环比不可计算的情况视为致命错误，阻止所有数据更新、通知和部署。重复运行仍会遇到相同缺口。这里的“历史不足”是比较月份不可用，不代表整个历史序列为空，也不是这条日志所指向的密钥错误。

本次未核实官方缺失该月份的原因，不对缺失原因作推断。

## 修复与验证

- 缺少比较数据的通胀指标保存为 `null`，保留最新参考月份和仍可计算的指标，并记录缺少的比较月份。
- 网页与邮件显示“暂无数据”；不补零、不跨月份替代比较，也不将旧期同比标为最新值。
- 网络失败、必需序列完全为空等校验仍保留。
- 27 项 Python 测试通过，覆盖四种通胀序列的同比、环比和两者同时缺失，以及邮件生成和空序列拒绝。
- Node 验证网页空值渲染、正常环比和 PCE 显示；JavaScript 语法检查通过。
- 同一份真实 FRED 数据修复后可生成仪表盘：2026-10 CPI 环比 0.4%，核心 CPI 环比 0.3%，两者同比为空，缺少的比较月份均为 2025-10。

验证使用 FRED 公开 CSV，未使用仓库 Secret 调用 API，未发送邮件或执行远端部署。本地修复尚需推送后由 GitHub Actions 验证线上完整流程。
