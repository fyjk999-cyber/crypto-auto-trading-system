# 第 05 章：全市场发现、事实历史与覆盖

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

把已有SWAP扫描扩展到既定产品范围，覆盖与执行资格分层。

前一章 04 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

opportunity/universe、scanner、history、API覆盖契约；选择性迁入历史工作树代码。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 保留ALL_MARKET/OBSERVABLE/ANALYSIS/EXECUTABLE；有真实行情但未触发因子的品种仍可进入轮换观察。
2. 低成交额/宽价差优先影响分析资源和执行风险，不把质量标签悄悄变成方向权威；安全排除保留原因。
3. 实际获取的bar数量/连续性决定指标可用，不能传配置candle_limit冒充数据。
4. 补bid_qty/ask_qty给盘口失衡工具；OI/funding缺失明确。
5. 日线全可得历史1Dutc断点续传、分页去重、限流、缺口/退市/到期处理；继承旧history collector有效实现，不覆盖dirty。
6. 提供earliest/latest/count/gaps/source_exhausted/last_error；source_exhausted不等于交易所从上市以来全量可得。

## 测试与回归

- 活跃集合+轮换公平性，非USDT产品发现，无因子触发仍可观察。
- 批量限制、请求配额、缺历史/不连续、下架、重试与断点恢复。
- 原始来源与API覆盖对账，不创建无限WS。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 品种数量和四层覆盖、历史覆盖表、迁移来源diff。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

不能把USDT SWAP全覆盖报告成OKX所有产品全覆盖。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
