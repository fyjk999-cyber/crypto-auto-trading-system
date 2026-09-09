# 第 06 章：统一计量、账本及真实风控

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

Risk/Portfolio/Fill/API同一经济事实；日亏损和回撤真正生效。

前一章 05 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

exposure、ledger、portfolio、risk、fills/projections、数据库恢复。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 线性notional=qty*price*contract_size*multiplier；反向按面值/结算币语义；SPOT按资产量，禁止重复本地公式。
2. 权威余额/已实现/未实现/费用/funding来自可追溯账本与事实价格；多币估值需汇率来源及时间。
3. 正式Risk.check传真实daily_pnl、peak/drawdown、已有敞口；缺信息不得默认零风险。
4. 成交落库/ledger/projection分步失败需outbox或已有可重放幂等机制；禁止重复记账。

## 测试与回归

- 各产品同一案例跨Risk/Portfolio/API/reporting对比无差异。
- 日亏损、回撤、旧价格/缺价格、资产单位触发测试。
- 中途数据库异常、重复fill、重启replay、journal平衡。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 金标准金额/公式，DB一致性查询、迁移前后统计。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

必须证明CANONICAL_NOTIONAL_MISMATCH=0；不能仅测Exposure helper。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
