# 第 08 章：工具驱动证据与策略质量

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

增强现有策略证据，不增加竞争性方向权威。

前一章 07 必须有绑定实际提交的 Codex APPROVED。待审只能只读预研。

## 允许修改与禁止范围

llm/tools、context_loader、alpha策略输出、研究/记忆只读适配。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 核对factor_intelligence等真实接线，区分命名存在与能力可用；工具只能读和计算。
2. 统一EvidenceItem的instrument/timeframe/as_of/source_refs/version/data_quality/signal_strength；概率未经校准为null，不能把0.8启发式当80%胜率。
3. 标记trend/momentum/breakout共用数据和证据依赖，输出反证、适用场景、失效条件。
4. 完善多周期、真实成交量、突破高低/假突破、均值回归趋势反证、funding/basis单位与持有期，不简单相加称套利。
5. 单工具timeout、global budget、schema及身份/未来时间校验；memory/research不是行情30秒TTL；研究结论非天然FACTUAL。
6. 接入组合相关性、交易成本、持仓MFE/MAE和原始风险距离证据；缺数据明确，不能伪造。

## 测试与回归

- 不同上下文Chief可选不同工具；无触发不禁交易；工具不创建plan/order/risk审批。
- 过期/异币/未来证据、工具timeout、重复证据、未经校准概率。
- 研究/记忆as-of和source可追溯，工具部分失败保留其他事实。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 能力清单、真实调用引用、证据schema版本、权限负测。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

新策略只作为工具；校准或threshold变化需第12章独立批准。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
