# 第 09 章：决策真相、调用节流与证据持久化

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

每次实际Chief请求都可追踪，不能只留audit摘要。

前一章 08 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

llm_chief schema/provider/orchestrator/decision_store、持久化迁移。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. FLAT仅LONG/SHORT/NO_TRADE/WAIT；OPEN仅HOLD/REDUCE/EXIT；非法为FAIL_CLOSED。
2. 应用生成decision_id；请求STARTED/SUCCEEDED/FAILED/CANCELLED/UNKNOWN恢复对账；崩溃不补造模型输出。
3. 记录provider/model/prompt/context/tool/schema版本和不可变证据快照；请求、选择工具、最终决定属于同Chief。
4. 每次调用及异常完成计入节流，保持真实token/timeout/retry/last_error且不泄漏秘密。
5. 金钱关键字段严格有限数值/Decimal语义、OPEN关键字段必填，额外/非法动作拒绝。

## 测试与回归

- NO_TRADE/WAIT/异常/取消后节流；跨重启去重。
- schema恶意/畸形/非有限/额外字段；模型自带ID不可信。
- 崩溃于request/persist间可恢复；证据hash/引用不变。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 决策状态查询、请求和版本链路、失败无订单证明。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

健康probe不能冒充真实交易决策调用。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
