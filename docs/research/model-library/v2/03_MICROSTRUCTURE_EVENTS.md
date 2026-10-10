# 订单簿、事件流、深度学习与队列理论（M13 / M14 / M18 / M23）

## 数学数据约定
best bid 价格 P^b、数量 Q^b；best ask 价格 P^a、数量 Q^a。订单簿快照仅反映某一时点的存量；逐笔交易、增量事件、撤单、改价反映流量；不可混为一谈。mid=(P^a+P^b)/2。主动买/卖、quote 时间戳、订阅序列号须可信，断连期间不能从稀疏快照推造事件。
**观察到的方向变化≠已成交净收益**。微观结构对短时预测的研究必须考虑价差、延迟、队列和逆向选择。

## M13 Order Flow Imbalance（OFI）
Cont–Kukanov–Stoikov 的最优买卖档变化可按相邻事件 n 表示：
$$e_n=1_{\{P^b_n\ge P^b_{n−1}\}}Q^b_n-1_{\{P^b_n\le P^b_{n−1}\}}Q^b_{n−1}-1_{\{P^a_n\le P^a_{n−1}\}}Q^a_n+1_{\{P^a_n\ge P^a_{n−1}\}}Q^a_{n−1}.$$
特定窗口 OFI=Σ_n e_n。该公式体现订单簿队列事件变化，不等同于只观察 bid_qty−ask_qty，也不等同于已成交的 CVD。与当期/随后价格变化关系须明确因果和预测时序，相关性不等于独立 Alpha。
**输入**：连续的有序 quote 增量、价格档位、数量与时间戳；若只有 1m 快照，标准事件型 OFI 不可识别。**局限**：队列深度依赖性、tick size、数据丢包、市场冲击，模型跨市场迁移不自动成立。**原文**：Cont, Kukanov & Stoikov (2014), The Price Impact of Order Book Events, DOI 10.1093/jjfinec/nbt003。

## M14 Hawkes 自激/互激过程
多变量事件类型 k 的指数核强度：
$$\lambda_k(t)=\mu_k+\sum_j\sum_{t_i^{(j)}<t}\alpha_{kj}e^{-\beta_{kj}(t-t_i^{(j)})}.$$
强度是每单位时间事件到达概率尺度，μ 为基线，α 为激发大小、β 为衰减，核积分矩阵元素 ∫φ_{kj}(t)dt=α_{kj}/β_{kj}；常见线性正核模型需要该矩阵谱半径 <1 的稳定性条件。
**估计**：完整事件时间戳/类型、极大似然、残差 time-rescaling；若事件只被聚合到分钟数据，需重新定义观测模型。**风险**：事件漏报、清算数据选择性缺失、截断、自激与共同外生冲击混淆。**案例**：买单簇、撤单簇、连锁清算的条件到达强度；高强度不代表某个方向必盈利。**论文**：Bacry, Mastromatteo & Muzy (2015), Hawkes Processes in Finance, DOI 10.1142/S2382626615500057。

## M18 DeepLOB（深度订单簿表示学习）
**理论结构**：把多个深度档位的价格/数量及历史时间步编码为二维时序张量，卷积网络提取空间特征、循环/序列网络处理时间依赖，使用 softmax 对预先定义的未来 mid-price 方向标签做分类。
若 logits z_k，则预测 p_k=exp(z_k)/Σ_j exp(z_j)，常用交叉熵 L=−Σ_k y_k log p_k。
**关键风险**：标签未来视野重叠、训练/测试泄漏、跨日/币种迁移、样本复制、缺失 L2 深度；高准确率也可能无法覆盖 spread+fees+latency。**论文场景**：原始工作以金融限价订单簿为对象，不能直接当 OKX 加密永续合约盈利证据。**论文**：Zhang, Zohren & Roberts (2019), DeepLOB: Deep Convolutional Neural Networks for Limit Order Books, DOI 10.1109/TSP.2019.2907260。

## M23 Queue Imbalance（队列存量不平衡）
$$QI_t=\frac{Q_t^b-Q_t^a}{Q_t^b+Q_t^a},\quad Q^b+Q^a>0.$$
常用于研究下一次 mid-price 变动的概率（如 logistic: P(up|QI)=σ(a+b QI)），需要明确买一/卖一档位定义、tick size 和 horizon。
**必须分辨**：Queue Imbalance 是公开最优档位数量的**不平衡指标**；Queue Position 是**自己挂单在队列里的位置**，不能单凭 QI 求得订单的真实排队优先级，也不能据此保证 maker 成交率。**案例**：论文分析股票订单簿的一跳价格方向，非加密成交率可直接迁移证据。**论文**：Gould & Bonart (2016), Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book, arXiv 1512.03492。

## 补充概念（不是另一个原 24 模型）
- **Signed markout**：对成交方向 s∈{+1买,−1卖}，M_Δ=s(m_{t+Δ}−p_fill)/p_fill 可描述成交后的带方向价格变化；改用 m_t 为参考可单独分离成交相对当时 mid 的付价。不等于总 realized PnL，也不等于已估计真实 queue position。
- **Adverse selection**：成交后市场持续向交易者不利方向移动，或 maker fill 倾向发生在不利报价更新前；区分价差成本、滑点、信号变动与有毒订单流。
- **订单生命周期**：提交、ACK、部分成交、取消竞争、UNKNOWN、实际全成交流水与资金账簿才是可追溯的交易事实；未成交机会只能报告反事实不确定性。

## 学术补充
Glosten & Milgrom (1985), Bid, Ask and Transaction Prices in a Specialist Market with Heterogeneously Informed Traders, DOI 10.1016/0304-405X(85)90044-3；说明价差与信息不对称的理论联系。不得把模型的理论方向预测精度自动视为零成本可实现利润。