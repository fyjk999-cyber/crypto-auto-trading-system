# 第 11 章：回测数值与事实回放修复

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

先修评价器，再评价策略。

前一章 10 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

governance/backtest、walk-forward/replay适配、指标测试。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 平多/平空盈亏按被平持仓方向计算，修复反手符号。
2. 手续费/滑点/funding计入净PnL及equity，逐期账户收益不同于入场累计收益。
3. 修正CAGR/Sharpe/Sortino/DD/averageR等未实现或错误指标，缺条件为不可用，不输出999当真实性能。
4. 真实时间/产品/数量/OHLCV输入；固定BTC/人工volume等仅标注测试；生产模拟不混入。
5. 复用统一Exposure/ledger计算，清理重复评价路径；LLM回放与规则策略回测分开。

## 测试与回归

- 手算多/空上涨下跌、反手、双边成本、部分平仓。
- 账户权益逐步核对、无交易/无亏损/不足样本、不规则时间。
- linear/inverse/spot、费用funding、最后一笔平仓规则。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 手算金标准、修复前后差异及不可用指标说明。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

禁止拿旧错误回测结果支持推广或参数优化。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
