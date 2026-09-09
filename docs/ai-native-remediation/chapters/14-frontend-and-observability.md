# 第 14 章：前端、接口与事实可解释性

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

在已有新页面上补真实可观察性，不另造后台。

前一章 13 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

frontend现有页面/hooks、只读API状态/覆盖/lineage契约。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 显示branch/HEAD/RUNNING_SHA及部署版本差异，lease/kill switch/reconciliation/Provider独立状态。
2. 覆盖页显示发现/观察/分析/执行集合、earliest/gaps/stale；工具缺失和候选来源清楚。
3. 决策原始→risk批准→订单/持仓→复盘一键可追溯。
4. 检查每个相关按钮API、权限、loading/timeout/retry、失败/0/空/缺失区分。
5. 不暴露keys或触发旁路订单；未配置明确显示，不把health拼成一律健康。

## 测试与回归

- frontend npm test/typecheck/build；真实浏览器操作与只读DB/API对账。
- 404/500/timeout、离线恢复、无数据、版本不同、无权限。
- 表单提交不重复、按钮不触发LIVE/秘密读取。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 路由/按钮矩阵、截图、API事实引用和错误状态证据。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

HTTP200或页面存在不等于全系统健康。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
