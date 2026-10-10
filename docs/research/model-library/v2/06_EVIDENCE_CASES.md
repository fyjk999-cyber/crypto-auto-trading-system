# 学术证据与案例索引（跨系统共用，不是优化方案）
版本：2026-10-11。本页只陈述明确支持的论文研究对象与边界；不声称论文里的交易收益可被三套系统复现。原始数学论文用于定义与推导；实证论文用于研究可检验的假设；最终运行事实只可能来自各自 PAPER 数据。

## 一、已核对的加密市场研究
### E01 多方法波动率比赛（适用于 M05/M12/M16 的理论比较）
**论文**：Forecasting cryptocurrencies volatility using statistical and machine learning methods: A comparative study, Applied Soft Computing 151 (2024), 111132。DOI https://doi.org/10.1016/j.asoc.2023.111132。
**研究对象**：BTC、ETH、LTC、XMR 日/周波动预测；比较 HAR、GARCH、LASSO、SVR、MLP、RF、LSTM 等 12 类方法。论文报告不存在跨币种、跨损失函数和预测期限一致获胜的唯一模型；某些线性模型不逊于复杂神经网络。
**可以推断**：需要把波动预测误差、预测期限与资产分别看待。**不可以推断**：某个模型能提升 Lowrisk 的 1m 净收益或 Turbo 的秒级方向正确率，也不可以把本文看作对你系统 fee-adjusted PAPER 的验证。

### E02 加密收益的日内动量与反转（M04/M11/M17 和现有 Momentum 对照）
**论文**：Wen, Bouri, Xu & Zhao (2022), Intraday return predictability in the cryptocurrency markets: Momentum, reversal, or both, North American Journal of Economics and Finance 62, 101733。DOI https://doi.org/10.1016/j.najef.2022.101733。
**研究对象**：BTC 高频历史观察（2013-03-03 至 2020-05-31）；还检查 ETH、LTC、XRP；在跳跃、流动性、FOMC、疫情环境下研究日内预测性质。
**研究认识**：动量与反转可以并存且依赖市场环境。**不可推断**：观察到最近几笔趋势交易亏损就一定应归为 OU 价差回归；此文不是对现有合约因子仓位的直接证明。

### E03 加密跨资产机器学习收益（M16、成本 / 全市场筛选）
**论文**：Cakici, Shahzad, Będowska-Sójka & Zaremba (2024), Machine learning and the cross-section of cryptocurrency returns, International Review of Financial Analysis 94, 103244。DOI https://doi.org/10.1016/j.irfa.2024.103244。
**研究对象**：2017–2023、超过 500 种加密资产及多个交易所，研究 40 种特征、8 种机器学习模型；论文报告价格、过去 Alpha、流动性及动量等简单特征的重要性，部分基于交易成本的收益仍为正，但收益与难交易的小币/高波动暴露关系密切。
**可以推断**：复杂度不是经济优势保证，且容量/费率与可交易性重要。**不能直接迁移**：多所现货/广泛资产横截面收益 ≠ 单一 OKX 永续合约、同一账户风险和真实可成交净利润。本库仍禁止跨所套利。

### E04 Order-Flow 与盘口变化（M13）
**论文**：Cont, Kukanov & Stoikov (2014), The Price Impact of Order Book Events, Journal of Financial Econometrics。DOI https://doi.org/10.1093/jjfinec/nbt003。
**案例性质**：订单簿事件与短期价格冲击的原始市场微观结构研究。**条件**：完整的事件序列、盘口最优档位变化。静态 bid/ask 深度或 OHLCV 不能替代 OFI 原始定义；论文不是 Turbo 的已验证实盘盈利案例。

### E05 Queue Imbalance（M23）
**论文**：Gould & Bonart, Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book, https://arxiv.org/abs/1512.03492。
**研究对象**：10 只 Nasdaq 股票，拟合队列存量不平衡对下一次 mid-price 方向的概率关系，大 tick 股票改善更明显。
**不可以迁移**：不能凭最优 bid/ask 的 QI 认定 OKX maker 订单的队列位置、真实成交概率或手续费后净利润。

### E06 EVT 对条件 VaR 与 Expected Shortfall 的建模（M08/M19）
**论文**：McNeil & Frey (2000), Estimation of tail-related risk measures for heteroscedastic financial time series: an extreme value approach, Journal of Empirical Finance。DOI https://doi.org/10.1016/S0927-5398(00)00012-8。
**研究方法**：将条件异方差建模与创新残差极值分布结合，以改进尾部风险预测。**边界**：研究的历史日回报风险结论不能被解释为“Turbo 1min 清算绝不会超过阈值”；异常市场时的流动性风险需单独考虑。

## 二、理论原文与实证案例之间不得混淆
- Black–Scholes/Heston 主要是衍生品定价理论；不是永续合约秒级 directional Alpha。
- Kalman/HMM/OU/GARCH 可以有数学推导，但参数估计不能直接证明市场可预测利润。
- Hawkes、DeepLOB 与队列模型往往需要很细的时序数据；若源是低频快照，研究主张标为 NOT_IDENTIFIABLE。
- Almgren–Chriss 是执行问题的数学框架；小账户实际主要成本可能为手续费、价差和未成交。
- DSR/White Reality Check 纠正样本内模型择优偏差；不产生新的市场信息。

## 三、Harness 实证报告如何引用本页
仅引用论文作者/年份/研究市场/频率/目标/DOI/结论边界。禁止给历史论文添加未经文献确认的精准年化收益率、胜率、成交量。任何本系统 PAPER 的亏损或盈利必须由当前系统实例的真实订单、成交与账本证据支持，不能以文献替代。

如两篇论文不同时间尺度或不同交易成本口径出现相反结论，不应称为逻辑矛盾，先指出研究设计差别。尚未查证/受限制全文的假设记为 ABSTRACT_ONLY，不声称阅读了全文附录。