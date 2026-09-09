# 第 04 章：指标、固定周期与市场状态

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

修复波动率与状态误判，保证每个品种和周期可复现。

前一章 03 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

alpha/features、market_data_engine、regime、evidence_router及相关测试。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. returns(n)提供足够收益率；缺失为不可用不是零；零波动/并列值分位不能被自动标为EXTREME_RISK。
2. 闭合K线与快照分离，盘口量不当成交量；真实OHLC高低点用于突破。
3. 按instrument/timeframe维护窗口，禁止跨币历史；初始默认兼容，不以修bug顺带改策略阈值。
4. 引擎容量有界，持仓pin、非持仓LRU/轮换；预热失败有退避重试与真实成功判断，达到上限时显式不可用。

## 测试与回归

- 已知收益率/波动手算、常数序列、样本不足。
- 同一时间不重复ingest；未来/乱序bar拒绝或隔离；重启一致。
- 超过40品种轮换、持仓保留、失败预热可恢复。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 金标准数据仅隔离测试，指标可用性和版本差异报告。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

不能用默认零或现价假装已计算完整指标。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
