# 状态估计、均值回归与变点理论（M04 / M06 / M11 / M15 / M17）
资料用途：定义数学条件和证据，不预设任何交易规则。

## M04 Ornstein–Uhlenbeck（OU）
**连续时间过程**：
$$dX_t=\kappa(\mu-X_t)dt+\sigma dW_t,\quad \kappa>0.$$
均值 μ，回复速度 κ，扰动 σ。期望条件为 E[X_{t+\Delta}|X_t]=μ+(X_t−μ)e^{−κ\Delta}；回复半衰期 t_{1/2}=ln2/κ。离散化为 AR(1)：X_{t+1}=a+bX_t+η_t，其中 b=e^{−κ\Delta}，只能在 0<b<1 等条件下按上述半衰期解释。
**识别**：常用于经证实平稳的价差、基差或残差，不是对所有单币价格的天然描述。价差组成关系的时间稳定性和交易成本需要单独验证；参数样本内拟合可能遭遇结构断裂。**理论案例**：同一交易所可观察的两个相关序列之差在稳定均衡附近扰动；是否可交易不可仅凭 OU 显著性判断。**论文**：Uhlenbeck & Ornstein (1930), On the Theory of the Brownian Motion, DOI 10.1103/PhysRev.36.823；Elliott, Van der Hoek & Malcolm (2005), Pairs Trading, DOI 10.1080/14697680500149370。

## M06 Kalman（线性高斯状态空间过滤）
状态方程 x_t=F_tx_{t−1}+B_tu_t+w_t，观测方程 y_t=H_tx_t+v_t，假设 E[w_t]=E[v_t]=0，噪声协方差 Q_t、R_t 且适当独立/高斯。
**预测**：x̂_{t|t−1}=F_tx̂_{t−1|t−1}+B_tu_t；P_{t|t−1}=F_tP_{t−1|t−1}F_t^T+Q_t。
**更新**：K_t=P_{t|t−1}H_t^T(H_tP_{t|t−1}H_t^T+R_t)^{-1}；x̂_{t|t}=x̂_{t|t−1}+K_t(y_t−H_tx̂_{t|t−1})。
**可识别性**：F/H 的可观测性、Q/R 噪声假设、真实观测间隔、缺失数据处理；超参数变动影响滞后与噪声过滤。**特别限制**：在线 filter 只使用 t 时点可知观测；后向 smoother 使用未来信息，不能作为历史“实时信号”。**案例**：观察带噪价格中的潜在趋势状态，但不能保证信号延迟、手续费后更有利。**论文**：Kalman (1960), A New Approach to Linear Filtering and Prediction Problems, DOI 10.1115/1.3662552。

## M11 HMM / Markov-switching（隐藏市场状态）
令潜在状态 z_t∈{1,…,K}，转移概率 A_{ij}=P(z_t=j|z_{t−1}=i)，观测 y_t 的状态条件密度 p(y_t|z_t)。
在线预测分布 π_{t|t−1}=A^Tπ_{t−1|t−1}，状态过滤后验
$$\pi_{t|t}(j)\propto p(y_t|z_t=j)\pi_{t|t−1}(j).$$
**估计**：极大似然、前向后向（训练阶段）、EM/Baum-Welch、信息准则；注意训练阶段可使用历史窗口内完整序列，而生产时点的估计不得引用 t 之后信息。**局限**：状态标签可交换；高频状态切换过拟合、状态持续时间假设与真实突变不符、极端风险罕见。**案例**：识别趋势/震荡/高波动的条件概率，而不是简单证明比 EMA 阈值好。**文献**：Hamilton (1989), A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle, DOI 10.2307/1912559；Rabiner (1989), Tutorial on Hidden Markov Models, DOI 10.1109/5.18626。

## M15 CUSUM / Bayesian Online Changepoint Detection
经典单边 CUSUM 可写为 S^+_t=max(0,S^+_{t−1}+x_t−k)；下降侧可定义 S^-_t=max(0,S^-_{t−1}−x_t−k)。k 为参考值，监测累计偏移而非一根 K 线异常。
Bayesian 变点模型把“距上次变点时间”r_t 作为运行长度变量，随新数据递推 P(r_t|y_{1:t})，涉及 hazard H(r) 和观测预测分布。
**输入/假设**：基线分布稳定、测量标准化、阈值误报率；BOCPD 需要 hazard 与共轭/近似预测分布。**评价**：变点检测延迟、平均虚警间隔、漏检、时点一致性；变点不必然等于趋势反转或可交易机会。**案例**：统计上识别价格/流动性过程出现结构变化的时期。**论文**：Page (1954), Continuous Inspection Schemes, DOI 10.1093/biomet/41.1-2.100；Adams & MacKay (2007), Bayesian Online Changepoint Detection, arXiv 0710.3742。

## M17 协整 / VECM（均衡关系与误差修正）
向量时间序列 y_t 若若干分量为 I(1) 且存在线性组合 β^Ty_t 为 I(0)，称存在协整关系。向量误差修正模型：
$$\Delta y_t=\alpha\beta^\top y_{t−1}+\sum_{i=1}^{p−1}\Gamma_i\Delta y_{t−i}+\varepsilon_t.$$
β 表示长期均衡向量，α 表示调整系数；与 OU 都可描绘回复，但 VECM 多变量且关注协整/调整机制。
**估计**：单位根、Engle–Granger / Johansen 协整检验、稳定性与参数不确定性；对制度变化、合约更替、样本筛选非常敏感。**案例**：同一交易所合约之间的经统计检验的长期价差关系；不含跨所套利。**论文**：Engle & Granger (1987), Co-Integration and Error Correction, DOI 10.2307/1913236；Johansen (1988), Statistical Analysis of Cointegration Vectors, DOI 10.1016/0165-1889(88)90041-3。

## 概念辨析
EMA/简单规则 Regime 与 Kalman/HMM 在功能上可能重叠但不是相同数学估计器；OU/VECM 的“价差均衡”不是单资产价格必然回归；检测变点只产生风险/状态证据而非自动交易权限。