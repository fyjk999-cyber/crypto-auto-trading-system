# LOWRISK — PAPER 亏损归因与备用数学模型知识库 v1.1
> Status: STANDBY / KNOWLEDGE-ONLY / REPORT-ONLY. 2026-10-11.
> 该文件是研究材料，不是策略配置、自动训练任务、上线授权或运行指令。不得因 PAPER 亏损而修改交易系统。

## 事实边界及双系统共享关系
- Lowrisk 当前受审基线来自历史 Round 1–4，历史部署 SHA `0697a6da512fb20c570ace40c655705fc4c6cc4d`；**监控时必须重新只读识别实际 runtime SHA 和实例**；仓库 main、文档分支均不代表正在运行的实例。
- 历史因子：`DET_MOMENTUM`、`X17_SUPPORT_RESISTANCE`、`X22_ORDERBOOK_IMBALANCE`、`X07_ATR_NATR`、`X24_MARKET_REGIME`；检查当前运行版本是否一致。原有 Trend / MeanReversion / Funding-Basis 不可当作未实现的新模型。
- Quant Core 的**相同策略包版本/输入快照**应产生相同因子证据和策略候选；但 Quant Core 用确定性决策、Lowrisk 可以使用独立 LLM 决策。不能以两套系统的最终交易不同推断“共享因子已分叉”；应追踪 `strategy_package_hash`、`factor_snapshot_hash`、`regime`、`candidate_id`、`decision_source`。
- 两套 PAPER 使用独立实例、账户、仓位、执行 lease 和资金账本。共享行情服务与历史数据只读；对相同市场事件需去重，不可把两套账户合并计算收益或样本独立性。
- 研究数据政策：最近 3 个月为拟合/选择候选窗口，较早 3 个月仅作逆时间回溯压力测试，不宣称前向 OOS；需后续真实时间推进的 Shadow/PAPER 验证。排除跨交易所套利。
- 历史审计涉及订单费用、合约乘数、maker 成交可证实性和 snapshot time-as-of；未经核实先归入 ACCOUNTING/DATA_BLOCKER，而不是 ALPHA 失效。
- 只读监控可读取事实、生成新报告（独立目录）；不得训练、回测、部署、更新参数/提示词、启停服务、写交易数据、下单、撤单、平仓、改变风险限额。

## 统一因果归因（亏损或未盈利 episode）
1. Factual ledger: 区分已实现净 PnL、未实现权益、外部现金流；逐笔费用、funding、滑点、清算费，禁止双计点差。
2. Order chain: 因子快照 -> 候选 -> LLM 决策 -> RiskDecision -> order/ack/fill -> 完整 episode -> realized PnL。拒绝/未成交不是亏损成交，不可制造反事实收益。
3. Pair audit: 与 Quant Core 在**同一时点同一策略 hash / 同样数据可用性**对比因子和策略输出；各自决策、下单与费用独立分析。无 hash 相等不得声称可对照。
4. Buckets: DATA_STALE / COST_MISMATCH / LEDGER_UNIT_ERROR / EXECUTION_COST / REGIME_MISMATCH / ALPHA_ERROR / TAIL_RISK / POSITION_CONCENTRATION / LLM_SELECTION_DIFFERENCE / INSUFFICIENT_EVIDENCE。
5. 必须比较盈利与亏损样本，12h/7d/30d，按 regime、币种、signal age、holding horizon、策略、成交方式分层；每一项解释写事实、反例和可信度。

## 候选模型目录（报告中最多推荐一个 PRIMARY + 两个 BACKUP）
| 编号 | 模型或公式 / 框架 | 可适用的观察 | 与现有基线的去重、证据与退出条件 |
|---|---|---|---|
| L01 | Cost-aware No-Trade: E[net edge|X] = E[gross move|X] - E[total execution cost|X] | 方向正确仍净亏、微利频繁被吃掉 | 对照无门槛策略；核实实费、未成交机会成本；费用未知则 BLOCKED |
| L02 | HAR-RV: RV(t+1)=b0+bd RV(d)+bw RV(w)+bm RV(m)+e | 波动状态预测滞后 | 对照 X07 / realized-vol / EWMA / GARCH；QLIKE 与净 PnL；历史跨度不足不造长窗 |
| L03 | GARCH(1,1): h(t)=omega+alpha e(t-1)^2+beta h(t-1) | 价格冲击聚集、风险门槛错配 | 预测方差 ≠ 方向 Alpha；须验证拟合收敛、鲁棒性和相对 L02 的增量 |
| L04 | HMM / Markov switching: P(z(t)|y(1:t)) | 趋势策略在震荡连续亏损 | 对照 X24 规则状态；只用 filtered probability，严禁含未来数据的 smoothed posterior |
| L05 | CUSUM / Bayesian online change point: S(t)=max(0,S(t-1)+x(t)-k) | 状态发生突变、短期异常 | 对照固定阈值、评估误报与检测延迟；不能自动停策略 |
| L06 | OU / VECM: dX=kappa(mu-X)dt+sigma dW | 单交易所存在经检验的均值回归价差 | 需价差平稳性、结构断点、半衰期及费用后回归；不假定所有币价回归 |
| L07 | 动态 OFI（订单事件流）vs 静态 X22 | 盘口撤单/跳价扰乱静态失衡 | 需真实增量订单簿顺序和 timestamps；无事件数据则 DATA_NOT_ELIGIBLE |
| L08 | EVT/POT + Expected Shortfall/CVaR | 尾部损失、多个币同步暴跌 | 与硬性 DD/kill switch 并行但不替代；尾部样本不足则 INSUFFICIENT_TAIL_DATA |
| L09 | DCC-GARCH / Ledoit-Wolf 收缩协方差 | 多币仓位看似分散却同跌 | 对照滚动相关；评价聚集风险和交易成本，不自动再平衡 |
| L10 | Kalman state-space / XGBoost 元预测 | 趋势潜在状态、非线性因子交互 | Kalman vs EMA；XGBoost vs logistic；严控延迟、后视特征、过拟合 |
| L11 | DSR / White Reality Check（研究控制） | 大量试参发现“最佳策略” | 所有候选必须记录完整试验次数、相关样本、置信区间及选择偏差 |

## 模型对照的指标及提案形态
- 统一对照：净 R-multiple、净 PnL、最大回撤、Expected Shortfall、换手率、maker/taker 成交率、每单总成本、NO_TRADE 机会损失、分环境稳定性、时延、基线一致性、不同币种/时间窗口稳健性。
- 区分 `DIAGNOSE` 与未来研究请求：每个候选需要问题证据、方法数学表达、必要数据、已有因子重叠、不能解决的问题、预计改善的可检验指标、推翻假说的失败标准、原始文献。
- 优先顺序：账本/费率/合约单位纠错**建议** -> 净边际过滤研究 -> L02/L03 模型竞争 -> L04/L05 状态模型 -> L08/L09 风险 -> L06/L07/L10 条件研究；**监控任务本身一项也不实施**。
- 发现同一策略源下 Quant Core 因子 parity 不一致时，标记 `STRATEGY_PARITY_BLOCKER`，仅报告要核对的 hash 与快照，不写共享策略包。
- 科学门禁：样本太少、相互依赖高、数据非 point-in-time 或真实成本不可验证，只能 `KEEP_OBSERVING` / `BLOCKED_DATA`，不得凭个别亏损“确认”模型失败。

## 核心论文索引（理论证据 ≠ 已验证 PAPER 盈利）
- Bollerslev 1986 GARCH, DOI:10.1016/0304-4076(86)90063-1
- Corsi 2009 HAR-RV, DOI:10.1093/jjfinec/nbp001
- Hamilton 1989 Markov-switching, DOI:10.2307/1912559
- Page 1954 CUSUM, DOI:10.1093/biomet/41.1-2.100; Adams & MacKay 2007 arXiv:0710.3742
- Uhlenbeck & Ornstein 1930 OU, DOI:10.1103/PhysRev.36.823; Engle & Granger 1987 DOI:10.2307/1913236
- Cont, Kukanov & Stoikov 2014 OFI, DOI:10.1093/jjfinec/nbt003
- Rockafellar & Uryasev 2000 CVaR, DOI:10.21314/JOR.2000.038; McNeil & Frey 2000 EVT, DOI:10.1016/S0927-5398(00)00012-8
- Engle 2002 DCC, DOI:10.1198/073500102288618487; Ledoit & Wolf 2004 DOI:10.1016/S0047-259X(03)00096-4
- Kalman 1960 DOI:10.1115/1.3662552; Chen & Guestrin 2016 XGBoost DOI:10.1145/2939672.2939785
- White 2000 Reality Check DOI:10.1111/1468-0262.00152; Bailey & Lopez de Prado 2014 DSR DOI:10.3905/jpm.2014.40.5.094

## 操作权限
**KNOWLEDGE_ONLY.** 每日 00:00/12:00 Asia/Shanghai 只读监控生成证据报告与方向。绝不触发训练、回测、自动参数选择/晋升、PAPER/LIVE 下单、撤单、恢复运行、服务配置/策略/数据库/知识库写入。报告独立写 `~/AI-Monitor-Reports/lowrisk/`；监控程序无此目录以外的业务写权限。报告只能建议未来由人另行授权的试验。
