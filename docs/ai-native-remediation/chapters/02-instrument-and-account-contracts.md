# 第 02 章：品种身份与多资产账户契约

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

SPOT、线性/反向 SWAP 和 FUTURES 不能共享模糊symbol或错误资金单位。

前一章 01 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

instrument/schema、mapper、账户契约、相关迁移；生产余额不可为验收修改。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 统一以venue+instId为品种身份，保留内部显示symbol兼容映射；携带instType/ctType/ctVal/ctMult/ctValCcy/settleCcy/expiry/lot/min/tick。
2. 移除强制LINEAR_PERP；身份和单位未知则禁止执行并说明原因。
3. 现货SELL仅卖持有资产；不引入借币做空；多币种抵押与账户计价明确，缺抵押币保持不可执行，不自动注资。
4. 迁移保留原ID及原始来源，无法确定产品的旧数据进入隔离待处理，不猜造。

## 测试与回归

- BTC现货/永续/到期/反向ID互不混淆；非BTC实例。
- 精度、规格缺失、退市/到期、抵押币缺失。
- 迁移升级/回滚或向前修复演练；历史证据不变。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 产品契约、兼容映射、迁移dry-run和隔离计数。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

不得把资产余额相加充当权益或把任何SELL都解释为空头。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
