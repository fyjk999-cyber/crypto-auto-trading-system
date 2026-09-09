# 第 15 章：发布、持续健康与自然验收

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

在固定已审版本上验证完整真实PAPER闭环。

前一章 14 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

发布清单/测试/受控运行与证据；不改策略补成交。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 完整backend pytest/Ruff/frontend tests/typecheck/build、迁移及恢复；agent-project-test需查真实配置，不存在明确N/A。
2. 提交固定SHA、DB路径、pending orders/positions、单writer、provider预算和启停回滚方案，等待Codex运行专项批准。
3. 连续24小时健康且跨UTC复盘时点，TTL后持续renew；真实OKX/DeepSeek、版本与lease/reconciliation一致。
4. 记录自然NO_TRADE/WAIT、LONG或SHORT入场到ACTIVE、OPEN review到事实EXIT/CLOSED、episode/review。
5. 自然无交易为PENDING_NATURAL_EVIDENCE，不调阈值/余额/时钟/价格/提示强迫交易。

## 测试与回归

- 无无计划entry订单/fill、无重复plan/decision/episode、无反向reduce、账本一致。
- 自然模型请求非health probe，真实ID和UTC时间链路完整。
- 中断恢复按安全授权；连续健康窗口故障后解释并重验受影响窗口。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 最终版本、完整命令退出码、24h健康、DB只读查询、自然entry/exit/learning的ID。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

工程/监督/运行/自然生命周期均PASS，且独立最终批准后才COMPLETE。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
