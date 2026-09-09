# 第 10 章：同Chief持仓管理与事实关闭

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

长期持仓从原始thesis到HOLD/REDUCE/EXIT闭环。

前一章 09 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

position_manager、TradePlan、runtime生命周期、订单/成交关联。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. OPEN携带原thesis/entry decision/plan/current facts/PnL/time/risk/memory/episodes及失效条件。
2. HOLD持久化不下单；REDUCE/EXIT目标量与事实剩余量核对、reduce_only、不穿零。
3. 先处理未结算entry取消/成交竞态，部分退出仍ACTIVE；只有投影qty=0才CLOSED。
4. 严格状态矩阵、重复同状态幂等、终态不可逆；expiry/cancel/invalidation真实事件关联。
5. 隔离legacy AIPositionBridge执行权；TIME_STOP仅真实max hold后备且走Risk/Execution；SHADOW→执行需专项授权。

## 测试与回归

- 真实build_system+受控Provider边界长短两套自动链路。
- 部分entry、REDUCE、部分EXIT、重复退出、重启、并发fill。
- HOLD零单/ACTIVE；提交单不关闭；legacy不能执行；无反转。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- decision-plan-risk-order-fill-position-close全ID与状态记录。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

隔离测试可用模拟Provider；不得把它们写为自然运行证据。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
