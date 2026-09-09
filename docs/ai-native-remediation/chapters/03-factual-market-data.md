# 第 03 章：真实行情与PAPER撮合输入

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

修复真实价格搭配固定深度；行情更新不能被LLM阻塞。

前一章 02 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

market_data、OKX public feed、PaperRealMarketAdapter、上下文投影和测试。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 传递真实价格和盘口档位数量；消除Decimal(1)深度及成交量占位值。
2. 独立有界行情任务，按instrument管理来源时间、接收时间、状态和序列；执行前获取新快照，保留决策快照。
3. 盘口序列缺口需重同步；REST/WS断线明确HEALTHY/STALE/DEGRADED/UNAVAILABLE，不换Binance/其他币/合成数据。
4. PAPER撮合显式标记模拟，盘口/成交证据与排队、滑点假设分开；无事实可成交依据不制造fill。

## 测试与回归

- 慢模型/超时不阻塞行情与续租；过期报价安全拒绝。
- 乱序/重复/丢序、盘口单位和部分成交、缺深度。
- 来源时间旧但接收新仍STALE；同symbol不同产品不串用。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 原始public响应脱敏引用、快照ID、模拟执行假设。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

不得放宽时效阈值来掩盖采集阻塞或制造成交。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
