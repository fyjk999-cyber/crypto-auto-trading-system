# 第 13 章：事实Episode、UTC复盘与记忆回流

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

会计计算归账本，原因解释归离线DeepSeek复盘。

前一章 12 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

governance/episode/scheduler/factual_learning、memory/research检索。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 事实full close唯一episode，包含原始及持仓决策、风险调整、全部fills、成本/funding、持有期、terminal reason。
2. UTC00:00审前日半开区间；SQL按时间过滤分页，不先截1000条；持久任务重试、补跑和幂等。
3. 原因分析区分判断/执行/成本/数据/偶然性，提取反证、lesson/pattern/coin profile并保留来源/置信度/适用范围。
4. 学习仅改善未来上下文，不修改live risk/execution/leverage/code；重复复盘同revision不重复增pattern。

## 测试与回归

- 跨UTC日、漏日、1000+条、重试、重复复盘。
- 无fill不产episode，部分reduce不关闭，重复close一个episode。
- 复盘Provider失败不影响会计事实，记忆as-of/反例及引用可重放。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- closed-trade→episode→review→memory→后续context证据。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

盈利标签不等于因果学习；净PnL不能由LLM编算。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
