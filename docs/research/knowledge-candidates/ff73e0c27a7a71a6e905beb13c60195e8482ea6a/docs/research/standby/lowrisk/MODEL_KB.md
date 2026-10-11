# LOWRISK — 推荐模型重点理论与亏损归因框架 V2
> 2026-10-11 · SYSTEM-FOCUSED THEORY · REPORT_ONLY · STANDBY
> **理论总库另存**：docs/research/model-library/v2/00_INDEX.md（24 模型与 6 专题）。这里不复制全库，而只展开和 Lowrisk 已有策略相联系的理论、识别条件与证据解释。本文不是策略优化方案；不包含参数设定、执行规则、策略权重调整、改造顺序或自动晋升许可。

## A. 现有策略定位与不可动基线
历史审计保留的因子家族：DET_MOMENTUM、X17_SUPPORT_RESISTANCE、X22_ORDERBOOK_IMBALANCE、X07_ATR_NATR、X24_MARKET_REGIME；原有 Trend/Breakout/MeanReversion/FundingBasis 与 LLM 决策等能力可能存在，必须以当前**实际运行**源码/策略哈希核对，不把文档分支当运行实例。
Lowrisk 与 Quant Core 复用同版因子定义和策略候选，最终 Lowrisk 的 LLM 决策与 Quant Core 的 deterministic decision 可合法不同；资金、订单、账本和决策事实不能互通写入。相同观察 hash 才具有因子 parity 对照意义。
监控对所有代码、服务、运行配置、数据库、策略包、模型 KB 只读，仅可产出独立诊断报告。

## B. 重点模型理论（详式及适用边界）
### LR-T1 交易成本与预期净收益（跨模型的经济恒等式，而非一个自动交易策略）
理论上的交易前净价值条件为 E[R_net|X]=E[R_gross|X]−E[C_fee+C_slippage+C_funding+C_other|X]，但“mid-price 变动”“可实际交割成交的价格变动”“账本已实现净 PnL”必须严格区分。买卖跨过 bid/ask 时产生价差，slippage 若基于 mid 与实际 fill 定义，价差可能已包含在内，不能再次相加。被动订单会存在未成交的选择偏差；未经观测的执行反事实不能当成真实损益。
**观察意义**：gross 正 / net 负是成本支配现象，不证明动量因子无方向预测性。论文基础：Glosten & Milgrom (1985), DOI 10.1016/0304-405X(85)90044-3；Almgren & Chriss (2001), DOI 10.21314/JOR.2001.041。

### LR-T2 HAR-RV、GARCH(1,1) 与 X07 的区别
X07 ATR/NATR 统计近期 K 线真波幅，ATR 衡量价格波动尺度而非严格概率预测；GARCH 的 h_t=ω+αε²_{t−1}+βh_{t−1} 模拟条件方差递推；HAR-RV 则 RV_{t+1}=β0+βd RV_t^d+βw RV_t^w+βm RV_t^m+e，表达多尺度已实现方差持续性。
**关键知识**：ATR、GARCH 和 HAR 的单位/目标不可混淆：NATR 是归一化波幅，GARCH 与 RV 在方差单位下比较前必须做一致的变换。GARCH 常见 ω>0、α,β≥0、α+β<1 用于有限无条件方差；HAR 的日/周/月应遵守 24/7 市场与窗口实际可用性。
**观测解释**：策略亏损与高波动重叠只代表条件关联，不足以确定“增加 GARCH 必赚”。估计精度以同口径 QLIKE/误差衡量，策略价值须另看可成交 net。Corsi 2009 DOI 10.1093/jjfinec/nbp001；Bollerslev 1986 DOI 10.1016/0304-4076(86)90063-1。
**加密案例边界**：2024 Applied Soft Computing comparative study DOI 10.1016/j.asoc.2023.111132，BTC/ETH/LTC/XMR 日周 RV 多模型没有通用赢家，不能外推分钟内 net edge。

### LR-T3 HMM / Markov Switching 与 X24 Regime
现有 X24 以已有特征阈值划分状态。HMM 隐变量 z_t 的转移矩阵 A_ij 和 emission p(y_t|z_t) 给出过滤后验 p(z_t|y_{1:t})；“过滤”与使用未来观测的平滑后验 p(z_t|y_{1:T}) 不同。状态模型允许市场模式不确定，而非用模型直接制定进出场指令。
**可识别性**：状态数 K、发射分布、转移稳定性、训练期标签交换及 regime drift。**观察问题**：亏损是否集中于具有不确定状态标签的区间；是否存在因子失效与状态测量滞后两个不同解释。Hamilton 1989 DOI 10.2307/1912559。

### LR-T4 CUSUM / 在线变点与结构失效
S_t^+=max(0,S_{t−1}^++x_t−k) 累计偏离；BOCPD 概率更新 P(r_t|y_{1:t}) 评估运行长度。改变状态 ≠ 自动逆转价格，也不意味着应修改 RiskEngine。
**可识别性**：变点的可检出大小、hazard、分布重尾、false alarms；原始策略判断错误与市场突然结构变化要分别标记。Page 1954 DOI 10.1093/biomet/41.1-2.100；Adams & MacKay arXiv:0710.3742。

### LR-T5 OU / 协整（与既有 MeanReversion 关系）
OU dX=κ(μ−X)dt+σdW，半衰期 ln2/κ；VECM Δy=αβᵀy_{t−1}+ΣΓ_i Δy_{t−i}+ε。**先讨论的数学对象**是证据支持的平稳价差/协整向量，不是价格上涨跌完“必然反弹”；依赖半衰期在持仓期限内稳定及结构断点识别。OU 均值回归和动量在不同观测期限可能同时存在。Uhlenbeck–Ornstein 1930 DOI 10.1103/PhysRev.36.823；Engle–Granger 1987 DOI 10.2307/1913236；Wen et al. 2022 DOI 10.1016/j.najef.2022.101733。

### LR-T6 X22 静态盘口失衡与动态 OFI
X22 是现有因子家族，但**实现计算口径需依本机 SHA**。事件型 OFI=Σe_n，e_n 来自最优买卖档位变更/挂单数量变化；不是仅由当前买卖一数量差得到的 QI，更不是 CVD（主动成交净量）。需要无缺口的 L2 顺序、双时间戳与 tick/合约规模；只有 1m K 线时不能宣称构造了标准 event OFI。Cont, Kukanov & Stoikov 2014 DOI 10.1093/jjfinec/nbt003。

### LR-T7 EVT/CVaR（分布尾部而非硬止损）
损失 L 的 VaR_q 是高损失分位点，ES/CVaR_q=(1/(1−q))∫_q^1 VaR_u du 是尾部均值；POT 假设高阈值超额近似 GPD，形状 ξ 与尺度 β 对罕见极端损失预测很敏感。传统“最大回撤阈值”和 Expected Shortfall 是不同数学对象。
**数据要求**：足够极端样本、价量质量、连续亏损相关性、fees/funding/清算事件；尾部估计不提供分钟止损“必达”担保。Rockafellar–Uryasev 2000 DOI 10.21314/JOR.2000.038；McNeil–Frey 2000 DOI 10.1016/S0927-5398(00)00012-8。

### LR-T8 多币相关风险（Markowitz / DCC / Shrinkage）
wᵀΣw 衡量共同二阶波动，而 DCC 让 R_t 随行情改变；协方差收缩缓解短样本不稳定。相关性非负尾部相关的替代物；多个币共同下跌可能不是单个币种因子失效。Markowitz 1952 DOI 10.2307/2975974；Engle 2002 DOI 10.1198/073500102288618487。

### LR-T9 Kalman、XGBoost 与统计控制（条件研究）
Kalman x_t=Fx_{t-1}+w_t、y_t=Hx_t+v_t，测量噪声 R 与过程噪声 Q 控制隐状态估计与滞后；XGBoost 是非线性损失最小化，不保证信号独立。DSR 和 White Reality Check 检验多次选型造成的偏差。Kalman 1960 DOI 10.1115/1.3662552；Chen & Guestrin 2016 DOI 10.1145/2939672.2939785；Bailey & López de Prado 2014 DOI 10.3905/jpm.2014.40.5.094。

## C. 非盈利事件的“理论归因坐标”（非优化方案）
| 观察到的事实 | 可能解释的数学主题 | 与事实不一致时应保留的替代理由 |
|---|---|---|
| 真实成交 gross>0，net<0 | 费用/滑点归属、成本条件期望 | 合约单位误计、funding、持仓时间、价差重复计费 |
| 净亏损集中在高波动期 | 条件方差、HAR-RV/GARCH、尾部 ES | 数据丢包、资金费、联动暴露 |
| 趋势信号在震荡期误判 | 状态 HMM、X24、OU/VECM | 预测期限、因子口径、LLM 选择差异 |
| 同类市场突然行为变化 | CUSUM/BOCPD | 时钟漂移、行情序列缺失、场所故障 |
| 多币同时亏损 | 协方差/尾部依赖 | 单一账户仓位集中、结算计价问题 |
| X22 指标和执行结果矛盾 | 静态失衡 vs 动态 OFI | 事件流缺失、买卖方向归因错误 |
| 同策略版的 Quant Core 与 Lowrisk 最终下单不一 | LLM 决策 vs 确定性决策差异 | 策略包、输入 as-of、风险/仓位不同 |

上述映射均为可能的解释，不允许据此断言因果或马上改变策略。每项理论解释需要列出支持/反驳事实、证据质量、无法观察项和学术来源；证据不足明确 INSUFFICIENT_EVIDENCE。

## D. 研究案例（仅解释，不触发执行）
- Wen et al. 2022, DOI 10.1016/j.najef.2022.101733：日内动量与反转共存，说明不同状态不能互相代替。
- Volatility comparative study 2024, DOI 10.1016/j.asoc.2023.111132：简单模型和复杂模型在不同币/期限胜负不一，不能按数学复杂度推定收益。
- Cakici et al. 2024, DOI 10.1016/j.irfa.2024.103244：流动性较差的小币上预测收益更难有效交易，不能直接迁移单所永续收益。

## E. Harness 只能输出研究方向
12h 监控只能读取真实订单/ledger/旧决策和知识库，描述根因候选及对应理论，不得提供可直接落地的阈值、权重、API 调用、代码补丁、调参命令、策略替换顺序。可以指出“该问题涉及 HAR-RV/GARCH 的条件方差研究”而非“把 X07 改成 GARCH 并设参数”。风险权限和现运行策略永久不受知识库授权影响。
