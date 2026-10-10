# 组合、资金增长与尾部风险理论（M07 / M08 / M09 / M19 / M21）
数学风险目标与交易方向 Alpha 不同；风险模型不得替代现行硬性风险权限。

## M07 Markowitz 均值–方差
给出多资产权重向量 w、预期收益 μ、协方差 Σ；常见形式
$$\max_{w\in\mathcal W} \big(w^\top\mu-\lambda w^\top\Sigma w\big),\quad \lambda>0.$$
或给定目标收益最小化 w^TΣw。**假设**：收益均值/协方差可被有意义估计，效用函数与风险度量匹配；协方差反映对称波动而不充分描述肥尾。**估计/局限**：样本均值不稳定、多资产多重共线、缩减协方差（Ledoit–Wolf）可缓解而非消除估计误差；有杠杆、永续资金费和交易成本时，预算/权重定义必须和保证金口径一致。**理论案例**：多个币种相关系数提高时，名义分散不一定意味着真实分散。**论文**：Markowitz (1952), Portfolio Selection, DOI 10.2307/2975974；Ledoit & Wolf (2004), A well-conditioned estimator for large-dimensional covariance matrices, DOI 10.1016/S0047-259X(03)00096-4。

## M08 Conditional Value-at-Risk（CVaR，也称 Expected Shortfall）
给定损失 L、置信水平 q，连续型常见定义 ES_q=E[L|L≥VaR_q]，一般分布及离散质量点须用更严谨的尾部积分定义 ES_q=(1/(1−q))∫_q^1 VaR_u du。
Rockafellar–Uryasev 样本优化形式
$$\min_{w,\zeta}\left[\zeta+\frac{1}{(1-q)N}\sum_{i=1}^N\max(L_i(w)-\zeta,0)\right].$$
ζ 为辅助 VaR 水平而非真实订单止损线。**条件**：需要可信损失情景、路径/相关依赖与账户一致的费用/清算假设。**不足**：历史罕见尾部、分布变化、高频跳价和流动性枯竭；CVaR 不保证单分钟绝不会超限。**案例**：多个币种同时剧烈回撤时，尾部损失与日常方差不同。**论文**：Rockafellar & Uryasev (2000), Optimization of Conditional Value-at-Risk, DOI 10.21314/JOR.2000.038；Artzner et al. (1999), Coherent Measures of Risk, DOI 10.1111/1468-0262.00028。

## M09 Kelly 预期对数增长
一项下注式概率模型：胜概率 p、盈亏比 b（每单位损失的净盈利倍数），最优无约束下注分数 f*=(bp−(1−p))/b，前提是交易结果独立同分布、概率和盈亏幅度正确且无额外约束。一般资产/组合形式
$$\max_w E[\log(1+w^\top R_{\text{net}})],$$
要求每个情景中 1+w^TR_net>0。
**局限**：估计错误敏感、厚尾/相关交易/强平/有限资产和手续费导致“理论高增长”不可靠；模型投票一致率≠校准胜率。分数 Kelly 是风险研究概念，绝不是自动提高杠杆的许可。**理论案例**：同样胜率、不同亏损尾部的两组策略，最优风险暴露可以截然不同。**文献**：Kelly (1956), A New Interpretation of Information Rate, DOI 10.1002/j.1538-7305.1956.tb03809.x；MacLean, Thorp & Ziemba (2010), Long-term Capital Growth: The Good and Bad Properties of the Kelly Criterion（可通过书籍/章节题名检索，具体版本需文献核对）。

## M19 极值理论（EVT / Peaks-over-Threshold）
超阈值 u 的超额 Y=L−u|L>u，常用广义帕累托（GPD）条件分布：
$$G_{\xi,\beta}(y)=1-\left(1+\frac{\xi y}{\beta}\right)^{-1/\xi},\quad \beta>0,\ 1+\xi y/\beta>0.$$
ξ 形状决定厚尾程度，β 尺度。样本阈值 u 的选择在偏差与方差之间权衡；独立同分布/弱依赖及极值近似只在适当条件下有效，条件波动聚集时常先标准化残差。
**估计**：阈值诊断、MLE、置信区间/Bootstrap、分层状态的尾部稳定性。**案例**：估计罕见异常损失条件分布；不能据此保证从未观察过的极端强平被完整覆盖。**文献**：McNeil & Frey (2000), Estimation of Tail-Related Risk Measures for Heteroscedastic Financial Time Series, DOI 10.1016/S0927-5398(00)00012-8。

## M21 CAViaR 动态条件分位数
不必先完整估计收益的概率分布，而是直接建模损失/回报的条件分位数。形式之一（自适应绝对收益型）：
$$q_t(\alpha)=\beta_0+\beta_1 q_{t−1}(\alpha)+\beta_2|r_{t−1}|.$$
注意 q 的符号和损失/收益方向应固定，式子为可用家族的一种而非全部 CAViaR。以分位数（pinball）损失等方式估计。
**验证**：实际超损频率、动态分位覆盖、序列相关、极端区间，和 ES 不同；超过阈值的幅度不能仅靠 VaR 得出。**理论案例**：波动状态变化时，风险分位水平随之变化而不必预设正态尾部。**文献**：Engle & Manganelli (2004), CAViaR: Conditional Autoregressive Value at Risk by Regression Quantiles, DOI 10.1198/073500104000000370。

## 风险体系概念边界
损失 q 分位 VaR、尾部均值 ES、概率校准、最大回撤、强平价、风险预算与 Kill Switch 是不同对象。危机时期相关性突变可能同时使 MV、DCC 与 EVT 拟合失效；使用任何模型都不能取消运行时硬约束。