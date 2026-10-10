# QUANT CORE V1 — 推荐模型理论与确定性决策归因框架 V2
> 2026-10-11 · SYSTEM-FOCUSED THEORY · REPORT_ONLY · STANDBY
> **独立的全量理论**：docs/research/model-library/v2/00_INDEX.md 包含原 24 项模型与案例；本文件只深化 Quant Core 的适用理论与诊断概念，**不是策略改造、回测、调参或部署方案**。

## A. Quant Core 独立系统定位
- Quant Core 是共享因子/策略包上的**确定性**交易决策系统，独立 PAPER 账本、风险及执行租约；不调用 LLM。Lowrisk 保留独立 LLM 选择，即使共用因子，也不保证最终方向、仓位或成交一致。
- 因子一致性定义为：同一 strategy_package_hash、feature_version、source dataset as-of timestamp/内容哈希、instrument contract 和缺失处理，产生同一因子值及共同策略候选。最终决策需另比较 decision_authority、risk、account state 和执行条件。
- 共享市场历史由原 canonical writer 维护，Quant Core 监控只读；不得推断本仓库的旧 main 就是实际正在运行的 Quant Core code。
- G0–G8 工程 PASS 不等于统计预测或 PAPER 净盈利；缺少交易事实时不得制造“低风险 Alpha”。

## B. 在 Quant Core 重点解释的模型理论
### QC-T1 可交易预期净优势：方向概率 ≠ 净收益
理论对象 E[R_net|X,a]：a 代表观测到的行为类型（买/卖/不交易），R_net=actual realizable PnL 减已计入的费用与资金费。未成交时没有 fill 价格，任何 hypothetical fill 必须标为不可证实反事实。执行的点差部分若已包含在实际成交价到 mid 的差中不能再计入一次。
**方向命中率**、**收益幅度**、**条件成交率**与**费用后价值**是不同随机量。没有可识别的交易成本分布，就不该把“因子预测正确”解释成“规则应当下单”。
理论参考：Glosten–Milgrom 1985 DOI 10.1016/0304-405X(85)90044-3；Almgren–Chriss 2001 DOI 10.21314/JOR.2001.041。

### QC-T2 共用的 X07 波动因子与 HAR/GARCH 竞争概念
ATR/NATR 抽取区间真波幅；GARCH(1,1) h_t=ω+αε²_{t-1}+βh_{t-1} 推断条件方差；HAR-RV 由日周月 RV 的线性部分预测下一时段。只在目标单位/频率/损失函数一致时才具备数学可比性。需要关注 ARCH 残差、自相关、长期方差是否存在和缺失 bar 的样本量。
该主题属于**共享因子理论**而非 Quant Core 独有模型，任何变化建议只能作为研究假设，不能自动调整共同代码包。Bollerslev 1986 DOI 10.1016/0304-4076(86)90063-1；Corsi 2009 DOI 10.1093/jjfinec/nbp001。

### QC-T3 共享 X24 状态、HMM 与 CUSUM
固定分位数/EMA 状态 X24 是确定性转换；HMM 使用状态转移矩阵 A_ij=P(z_t=j|z_{t−1}=i) 和过滤后验 p(z_t|y_{1:t})，CUSUM 累计相对于参考分布的偏差。这些都是**解释何时环境可能变化**的数学工具，不是直接生成风险审批或下单许可。
HMM filtered vs smoothed 必须区分，CUSUM 虚警与跳价识别也要区分；市场真实结构变更与数据 feed 中断是不同原因。Hamilton 1989 DOI 10.2307/1912559；Page 1954 DOI 10.1093/biomet/41.1-2.100。

### QC-T4 Kalman 对共享趋势/噪声因子的解释
线性状态空间 x_t=Fx_{t−1}+w_t，y_t=Hx_t+v_t；Q 与 R 决定预测误差与噪声过滤之间关系。卡尔曼滤波估计的是潜在状态，趋势滤波存在时滞，后向平滑不可被当成 t 时点实时信号。与现有 EMA/Momentum 功能可能高度重叠，需区分数学估计方法与新增预测信息。Kalman 1960 DOI 10.1115/1.3662552。

### QC-T5 OU、VECM 与趋势策略的互斥/共存条件
OU 近似在平稳价差 X_t 上的均值回复，半衰期 ln2/κ；VECM 用 βᵀy 的协整项和 α 调整向量刻画多个非平稳序列的稳定组合关系。它们并非“任何币种涨多了就跌”的数学证明。最近三个月窗口可产生显著性幻觉，结构突变和执行费用尤其关键。Wen et al. 2022 DOI 10.1016/j.najef.2022.101733；Engle & Granger 1987 DOI 10.2307/1913236。

### QC-T6 X22 的静态盘口因子 vs OFI
静态不平衡反映最优档位存量；OFI 是连续买卖报价变化事件 e_n 的有符号和，CVD 是成交主动方累计差。三者不能混称一个“盘口买压”而重复权重；也不能没有 L2 增量就假称已有 OFI。Cont et al. 2014 DOI 10.1093/jjfinec/nbt003。

### QC-T7 EVT/CVaR 与独立风险账本
CVaR_q=(1/(1−q))∫_q^1 VaR_u du；EVT 用极值样本尾部 GPD 拟合极端损失。统计上更低 ES 不等于账户不会强平，现有 hard risk 和 kill switch 仍是唯一授权层。因不同资金、杠杆、方向与成交条件，Quant Core 的尾部估计不能拷贝 Lowrisk 的风险结论。Rockafellar–Uryasev 2000 DOI 10.21314/JOR.2000.038；McNeil & Frey 2000 DOI 10.1016/S0927-5398(00)00012-8。

### QC-T8 多币组合相关性、XGBoost、统计筛选偏差
Markowitz 的 wᵀΣw、DCC 的随时间变化相关性是组合风险描述，并非方向 Alpha；XGBoost 的非线性拟合在短样本频繁重调时容易诱发 data snooping。DSR 与 White Reality Check 可审视试验选择偏差，不能当作已发现独立信号。Markowitz 1952 DOI 10.2307/2975974；Engle 2002 DOI 10.1198/073500102288618487；Chen & Guestrin 2016 DOI 10.1145/2939672.2939785；Bailey & López de Prado 2014 DOI 10.3905/jpm.2014.40.5.094。

## C. 三段式归因框架（不是实施步骤）
1. **共享因子证据层**：两个系统真正有同版策略与同样 as-of 输入吗？同个 market state 的因子和 candidates 是否一致？不一致先标记 PARITY_NOT_IDENTIFIABLE，而非确认共享策略失效。
2. **确定性规则选择层**：在因子与 candidates 相同的情况下，Quant Core 的 deterministic decision 怎样分派 NO_TRADE/LONG/SHORT/HOLD 等？它与 Lowrisk LLM 决策差异可观察，但其优劣需可比较的同条件交易机会，不能用一笔事后盈利证明。
3. **独立执行与账本层**：实际是否成交？成交质量、持仓时间、net/gross PnL、资金费、合约 ctVal、外部现金流与风险拒绝是否正确？不能将 Lowrisk 的交易回执代替 Quant Core 的账本。

## D. 未盈利事件 → 理论问题（只输出可能的研究方向）
| Quant Core 真实观察 | 对应研究领域 | 常见替代解释 |
|---|---|---|
| 同候选因子成功预测方向、最终净亏 | 可交易净价值、成交费用理论 | 报价/成交价口径混淆、部分成交、funding |
| 与 Lowrisk 有相同因子但决策不同 | 确定性决策 vs LLM 策略选择的统计对照 | as-of 数据、账户风险或不同候选版本 |
| 同一种 regime 中策略频繁失效 | HMM/CUSUM / X24 市场状态 | 数据断连、短样本或分时频率不匹配 |
| 多币种同方向损失 | 组合方差、相关/尾部依赖 | 共享 Beta 暴露、资金账本计价 |
| 盘口信号与后续变化矛盾 | X22 静态不平衡/OFI | L2 数据不连续或因果时序失真 |
| PAPER 没有真实闭仓 episodes | INSUFFICIENT_EVIDENCE | 不得从模拟成功率创造实际盈利概率 |

## E. 独立案例及文献边界
- Cakici et al. (2024) DOI 10.1016/j.irfa.2024.103244：跨资产 ML 研究说明简单特征的重要性，但覆盖多交易所与难交易资产，不能当作单所 Quant Core 的可实现收益。
- Wen et al. (2022) DOI 10.1016/j.najef.2022.101733：动量和反转并存，是环境分层的案例而不是强制更换方向策略的证据。
- 2024 多模型波动预测论文 DOI 10.1016/j.asoc.2023.111132：不存在对全部币种/预测周期通吃的波动模型。

## F. Harness 输出边界
每 12h 只记录 FACT / UNKNOWN / PLAUSIBLE_EXPLANATION / COUNTER_EVIDENCE / LITERATURE / POSSIBLE_RESEARCH_DIRECTION；不写参数阈值、改造代码、策略排序实施方案、实验脚本或上线计划。不训练、不回测、不部署、不修改共享策略。保持账户、资金、MarketHistory 和三套系统完全隔离。
