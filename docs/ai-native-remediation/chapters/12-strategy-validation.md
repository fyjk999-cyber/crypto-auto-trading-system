# 第 12 章：样本外验证与策略研究审批

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

评估实际工具/策略增量，不以收益幻觉驱动上线。

前一章 11 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

validation/replay/research的离线能力，参数变更提案；不改运行阈值。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 真正按时间训练/验证/测试，冻结最终测试集，重叠标签purge，保留退市与不可得历史边界。
2. 分别报告long/short、币种、周期、regime、交易成本、样本数/不确定性和失败案例。
3. 同数据做工具消融/证据去重对照，未校准confidence不声称胜率。
4. 今日LLM潜在历史知识泄漏不可消除时说明局限；真实前向SHADOW独立验证。
5. 任何参数/策略优化提案记录before/reason/evidence/change/test/shadow/rollback，Codex单独批准，不因交易少调参。

## 测试与回归

- 时间边界、防未来数据/存活偏差、测试集不可回灌。
- 完整失败报告、成本敏感性、样本不足标未验证。
- walk-forward确实执行窗口，不只是输入performance生成score。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 实验manifest/dataset hash/版本、失败样本、样本外结果、推广决议。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

研究通过不自动取得执行权或覆盖风险规则。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
