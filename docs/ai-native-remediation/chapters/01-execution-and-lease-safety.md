# 第 01 章：执行、撤单与租约安全

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

所有订单变更在事实有效的执行租约和授权之下；修正 c928368 撤单发生于校验之前的路径。

前一章 00 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

runtime/engine.py、lease、ExecutionAuthority、订单取消契约及相关测试；不改方向策略。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 将订单归属、plan/decision/symbol、操作权限、owner/token/fence 核验前置到下单/撤单/改单。
2. 审查 fc244d4 同 owner 自然过期恢复与 release tombstone 语义；不得重写已正确组件，也不能未经证据接受其安全性。
3. 失租约暂停可变更路径并受控停止；只读行情独立保留；若保持同进程恢复，必须证明新 generation、无失效写入窗口和唯一 writer，否则采用正常停止重启。

## 测试与回归

- 错误token/owner/fence、过期/显式release后恢复、renew异常/false。
- 合法未结算开仓取消、伪造持仓动作、重复取消、并发抢租约。
- 故障后执行拒绝；首TTL后持续续租、重启唯一writer。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 订单调用边界记录，失权期间零变更请求。
- 当前代码、运行、DB lease/health一致性证明；不得手改lease。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

旧writer仍可撤单或安全性未知，拒绝批准。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
