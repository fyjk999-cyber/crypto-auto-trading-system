# 第 07 章：仓位归一化、杠杆与成本

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

同一TradePlan通过确定性Sizing及Risk缩量进入执行。

前一章 06 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

sizing/risk/order metadata、成本证据工具；不修改方向或增加频率。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 按equity/risk budget/invalidation/vol/liquidity/exposure/spec确定数量，向安全方向舍入，低于最小手数拒绝而非加大。
2. 保留original/approved qty、requested/approved leverage及支持/反对风险证据；LONG/SHORT保持不变。
3. no fixed fallback；置信度不直接映射杠杆；Risk clamp后无需第二次Chief确认。
4. 费用/价差/滑点/funding按持有期和产品形成可解释成本证据，不做第二方向脑。

## 测试与回归

- long/short批准/缩量/拒绝；大小账户、高低波动、min lot、非1contract size。
- 无效/缺失/非有限杠杆、超过上限、流动性限制。
- 批准qty/leverage真正到达OrderIntent，ID和方向保持。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 原始→sizing→risk→order逐字段对照。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

不能用调大默认余额、放松风险或固定0.001通过验收。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
