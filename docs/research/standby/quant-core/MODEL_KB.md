# QUANT CORE V1 — PAPER 亏损归因与备用模型知识库 v1.0
> 2026-10-11 / STANDBY / KNOWLEDGE-ONLY / REPORT-ONLY. Quant Core 是独立 PAPER 系统，不是 Lowrisk 的第二个交易账户合并口径。
> 设计权威参照同仓库 `docs/quant-core-v1/SPAC.md` 与 `GOAL.md` 的固定版本，Quant Core 实际运行目录、代码版本和最近 SHA 必须从本机 runtime 只读确认；本知识库不宣称本仓库已包含全部 Quant Core 已实现代码。

## 系统角色和共享策略契约
- Quant Core：无 LLM 的确定性因子计算与策略决策，动态全市场扫描，自己持有独立 PAPER 风控、账本、执行 lease 和决策轨迹。
- Lowrisk：复用同版本的策略包/因子定义，但保留单独的 LLM 策略选择和独立 PAPER 执行/账户。**共享策略 ≠ 共享全部交易**。
- 同一 `strategy_package_hash` + 同一 `factor_version` + 同一 `asof_time`/输入哈希 + 同样的缺失处理 => 应重现相同因子值与候选策略，允许最后的 deterministic/LLM Decision 不同；单列差异出现的环节。
- Quant Core 不允许修改 Lowrisk 策略共享包，Lowrisk 监控也不允许修改 Quant Core 策略；只有共同版本哈希已确认才能做 parity。
- 共享的 OKX / SharedMarketHistory 行情只能由原 canonical writer 维护，三个监控任务均以只读方式访问，禁止新增行情采集器或第二 writer。
- Quant Core 与 Lowrisk 的 PAPER 账户、orders、episodes、权益、fees、funding、liquidation、仓位永远分别对账；相同市场窗口不是两次独立 Alpha 样本。
- 历史 audit：`DET_MOMENTUM`、`X17_SUPPORT_RESISTANCE`、`X22_ORDERBOOK_IMBALANCE`、`X07_ATR_NATR`、`X24_MARKET_REGIME`；Funding/Basis/OI 时点来源需要验证；`X21` 可能只是一种未训练代理，不得当成已训练的 ML 决策模型。
- Quant Core 的 G0–G8/工程测试 PASS 只能证明工程验收，不代表盈利；不以过去聊天中的 commit 作为当前 runtime 事实。
- 研究限制：最近 3 个月模型设计和时间顺序的滚动验证；更早 3 个月做逆时间压力测试（不是前向 OOS）；后续真实时钟 Shadow/隔离 PAPER 才能验证。单交易所，禁止跨所套利。

## 只读监控归因步骤
1. 冻结本窗口的 Quant Core 实例、运行 SHA/来源、PAPER 账户和 event id；读出完整 strategy hash、factor hashes、决定性决策与风控、订单及成本事实。
2. 重新检查 ledger: 已实现 vs 未实现 PnL，fees/funding/slippage/forced liquidation，外部资金流；full fill/partial/no-fill/rejected 状态。不能用缺失数据“补齐”事实。
3. 区分 QUANT_FACTOR_ERROR（共享因子问题）、QUANT_RULE_ERROR（确定性决策错误）、RISK_FILTER_ERROR（已记录的拒绝逻辑）、EXECUTION_COST、REGIME_CHANGE、DATA_QUALITY、UNIT/ACCOUNTING、INSUFFICIENT_EVIDENCE。
4. **跨系统证据（只读，授权可见时）**：匹配 Lowrisk 同窗口相同 `strategy_package_hash`、输入可用时间、候选因子集合；报告 `FACTOR_PARITY` 与 `STRATEGY_CANDIDATE_PARITY`，再单列 `DECISION_DIVERGENCE`。不可访问 Lowrisk 时 `CROSS_SYSTEM_NOT_VERIFIED`，不得推断一致或矛盾。
5. 为 Quant Core 生成**自己的**盈利/亏损对照与 12h / 7d / 30d 趋势，避免把 Lowrisk LLM 结论写成 Quant Core 确定性规则的实际结果。
6. 每窗口最多一个 PRIMARY 和两个 BACKUP 研究方向，只能生成报告，不能启动任何优化流程。

## Q-M 候选模型卡片（必须标注是共享因子层还是 Quant Core 专有决策层）
| 编号 | 候选及研究式 | 映射层 / 何时建议 | 已有能力及验证门槛 |
|---|---|---|---|
| Q01 | Cost-aware no-trade / net edge = gross edge - verifiable cost | Quant Core 确定性决策门槛；方向基本对但净收益负 | 与现有静态费用/risk gate 对照；未知填单概率、未成交流动性时不给确定结论 |
| Q02 | HAR-RV vs GARCH(1,1) vs X07 | 共享因子层；震荡/高波动期波动率描述不足 | 与 ATR/NATR/EWMA 对比 point-in-time QLIKE + 成本后收益，不重复投票 |
| Q03 | Markov-switching/HMM vs X24 | 共享状态层；原有 regime 标记延迟 | filtered probability 不包含未来，和固定阈值公平对照 |
| Q04 | CUSUM / Bayesian change point | 共享状态的失效诊断；突然的状态断裂 | 记录误报、检测延时，不自动终止/调整运行策略 |
| Q05 | Kalman online state-space vs EMA | 共享潜在趋势状态；噪声影响因子 | 不能用平滑后验中的未来观测；控制短时延 |
| Q06 | OU/VECM only for stationary spread | 共享策略候选层；区间价差具有经济联系 | 半衰期、断点、交易成本和平稳性全部符合；不用现货价格无条件均值回归 |
| Q07 | Event-based OFI vs static X22 | 共享微观因子层；静态盘口失衡被撤单扰乱 | 真实有序 L2 events，否则 DATA_NOT_ELIGIBLE |
| Q08 | EVT + CVaR risk stress | Quant Core 独立风险研究；肥尾、跨币相关暴跌 | 不降低现有 hard risk gate；尾部样本不足时不给置信结论 |
| Q09 | DCC / shrinkage covariance | Quant Core 独立组合建议；高度相关的持仓集中 | 仓位只做反事实建议，不允许动态再平衡 |
| Q10 | XGBoost meta / constrained rules | Quant Core 确定性元决策**未来对照方案** | 不等于引入 LLM；需比规则基线、logistic，控制标签时点与试验次数 |
| Q11 | White Reality Check / Deflated Sharpe | 公共实验验收控制 | 所有试验一并记录，禁止只报告最佳参数 |

## 错误诊断与归属
- 同时相同输入相同 hash 因子值不一致：`PARITY_BLOCKER`，先报告数据对齐/缺失/时钟/版本问题，不推荐新 Alpha。
- 因子完全相同、Quant Core 下单亏损、Lowrisk 没有下单：比较确定性 candidate→decision 与 Lowrisk LLM→decision，不能直接说共享因子无效。
- 两者同信号同方向同时净亏：说明共享市场风险或共同因子可能有关，仍需查单独费用/资金费/执行是否不同。
- 方向正确但 Quant Core 收益为负：优先 Q01 成本/no-trade 与成交事实，不优先 Q10 复杂模型。
- 低波动期反复假突破：比较 Q03 与现有 X24，随后 Q04/Q06，禁止以单窗口损失改策略权重。
- 无真实闭仓 episodes 或只有单一行情事件：`INSUFFICIENT_EVIDENCE`。

## 候选研究的前置条件（仅提出申请，监控不执行）
相同数据口径+候选 hash 对照 -> point-in-time 数据审查 -> 费用/成交有效性 -> 隔离训练/回测 -> 时间顺序 walk-forward -> Shadow -> 独立 PAPER -> 人工批准。监控只允许到 HYPOTHESIS 并输出实验设计；所有改变还需要在 Quant Core 和 Lowrisk 之间再次校核共享策略版本契约。

## 学术文献
- Bollerslev (1986) DOI:10.1016/0304-4076(86)90063-1; Corsi (2009) DOI:10.1093/jjfinec/nbp001
- Hamilton (1989) DOI:10.2307/1912559; Page (1954) DOI:10.1093/biomet/41.1-2.100
- Adams & MacKay (2007) arXiv:0710.3742; Kalman (1960) DOI:10.1115/1.3662552
- Uhlenbeck & Ornstein (1930) DOI:10.1103/PhysRev.36.823; Engle & Granger (1987) DOI:10.2307/1913236
- Cont, Kukanov & Stoikov (2014) DOI:10.1093/jjfinec/nbt003
- Rockafellar & Uryasev (2000) DOI:10.21314/JOR.2000.038; McNeil & Frey (2000) DOI:10.1016/S0927-5398(00)00012-8
- Engle (2002) DOI:10.1198/073500102288618487; Ledoit & Wolf (2004) DOI:10.1016/S0047-259X(03)00096-4
- Chen & Guestrin (2016) DOI:10.1145/2939672.2939785; White (2000) DOI:10.1111/1468-0262.00152
- Bailey & Lopez de Prado (2014) DOI:10.3905/jpm.2014.40.5.094

**强制安全声明**：知识库只读，不赋予 API/order 权限。Harness 只允许读取与产出独立报告，绝不修改策略、源代码、配置、数据、risk/kill switch、定时服务或线上进程。
