# 执行、非线性预测、多期控制与统计验证（M10 / M16 / M22 / M24）

## M10 Almgren–Chriss（最优执行成本）
经典问题在给定总订单量和执行期限内权衡预期冲击成本与库存暴露的价格风险：
$$\min_{\{x_t\}}\ E[C(\{x_t\})]+\lambda\mathrm{Var}[C(\{x_t\})],\quad \lambda\ge0.$$
x_t 为剩余库存路径；其成本区分永久/暂时市场冲击及价格随机性。市场冲击函数、无信息漂移、可执行离散订单等假设必须明确。
**适用场景**：大规模或分时执行的理论研究。**小资金永续注意**：手续费、跨价差、下单最小量、排队等待、未成交机会成本和资金费可能比自身冲击主导；不能把传统执行最优路径直接作为秒级限价单策略。**评价概念**：implementation shortfall、maker/taker 实费、realized spread、订单到成交延迟、queue information、现金流。**文献**：Almgren & Chriss (2001), Optimal Execution of Portfolio Transactions, DOI 10.21314/JOR.2001.041；Glosten & Milgrom (1985), DOI 10.1016/0304-405X(85)90044-3。

## M16 XGBoost（梯度提升树）
函数逼近 F(x)=Σ_{k=1}^K f_k(x)，每轮优化可利用损失二阶 Taylor 近似：
$$\mathcal L^{(t)}\approx\sum_i [g_i f_t(x_i)+\tfrac12 h_i f_t(x_i)^2]+\Omega(f_t).$$
g、h 为损失一二阶导，Ω 为树复杂度惩罚；适合结构化的非线性特征交互。
**可解释目标**：方向分类、预期回报回归、成交条件概率、风控风险分层是不同任务。**误区**：用当期已知特征训练未来事件标签时，时间窗口重叠、标签泄漏、频繁筛参会使准确率虚高。**评估**：时间顺序验证、对数损失/校准曲线、特征稳定性、净收益和运行延迟，不能只比较 AUC。**案例**：因子 X07、X22、X24 存在非线性交互，模型可以拟合但不等于可执行独立 Alpha。**文献**：Chen & Guestrin (2016), XGBoost: A Scalable Tree Boosting System, DOI 10.1145/2939672.2939785。

## M22 Model Predictive Control（MPC）/ 多期凸交易优化
在每一期基于预测状态、动态约束与风险/交易成本目标优化未来 H 期轨迹，经典形式：
$$\min_{\{u_{t:t+H-1}\}}\sum_{\tau=t}^{t+H-1}\ell(x_\tau,u_\tau)+V_T(x_{t+H})$$
满足 x_{\tau+1}=Ax_\tau+Bu_\tau 等状态约束；MPC 理论上只执行当前第一步并重复规划，但**本知识库只介绍概念，不授权任何动作**。
**交易变量**：持仓、目标暴露、订单执行成本、换手及现金/杠杆风险。**假设与风险**：预测误差、过度交易、不可凸的挂单成交概率、不可识别的延迟与实际撮合约束，需确保约束对生产权限无任何越权。**案例**：多周期风险与成本之间的数学权衡。**文献**：Boyd et al. (2017), Multi-Period Trading via Convex Optimization, arXiv 1705.00109。

## M24 Deflated Sharpe Ratio（DSR）
**研究问题**：重复试验、择优报告、非正态收益会让最佳样本 Sharpe 高估。DSR 把观察到的 Sharpe 相对多重试验下的基准极值并考虑偏度、峰度、样本长度。典型经偏度/峰度修正的统计量：
$$Z=\frac{(\widehat{SR}-SR_0)\sqrt{T-1}}{\sqrt{1-\widehat\gamma_3\widehat{SR}+\frac{\widehat\gamma_4-1}{4}\widehat{SR}^2}}.$$
其中 T 为有效样本量，γ3、γ4 为偏度和**非超额**峰度；SR_0 的选取与有效独立试验数有关，不能仅以尝试的名字个数替代相关模型的有效试验规模。
**假设与边界**：净收益、重叠窗口、策略相关性、非独立事件必须纳入；DSR 是对研究统计置信度的检查，并不会提升原策略收益。**文献**：Bailey & López de Prado (2014), The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality, DOI 10.3905/jpm.2014.40.5.094。

## 补充：White’s Reality Check（多重检验）
White (2000), A Reality Check for Data Snooping, DOI 10.1111/1468-0262.00152。通过重采样校正对多个交易规则反复筛选造成的择优偏差。Bootstrap 方法、交易事件依赖及全量模型搜索日志影响统计有效性。此法属于研究验收，不是交易预测模型。

## 独立于模型的净成交价值概念（附录）
对于可执行行动 a，理论经济价值应区分 P(fill|X,a)、成交条件下的价格变动、手续费、滑点、资金费、未成交流动性及等待机会成本。不同成本口径必须先定义是否已含 spread；不可把 quote crossing 重复计价。
真实订单可能没有成交、部分成交或在未知状态；不能用模型预测的中间价变化冒充 realized PnL。
**理论参考**：Glosten & Milgrom (1985), DOI 10.1016/0304-405X(85)90044-3；Almgren & Chriss (2001), DOI 10.21314/JOR.2001.041。
