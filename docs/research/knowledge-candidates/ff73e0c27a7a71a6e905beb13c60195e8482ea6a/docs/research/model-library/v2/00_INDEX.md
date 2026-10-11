# 数学模型理论总库 V2 — 全部 24 项（跨系统理论，非优化方案）
版本：2026-10-11。状态：KNOWLEDGE-ONLY / REFERENCE / NO TRADE AUTHORITY。

## 本库的作用与边界
本库为 Lowrisk、Quant Core、Turbo 共用的**数学与学术理论层**，只解释“模型是什么、数学假设是什么、什么数据才能识别、如何评估结论、什么情况下结论无效”，不包含策略改造命令、实盘参数、部署步骤、买卖阈值或自动优化指令。三套系统的重点模型与观察框架放在各自 MODEL_KB.md，周期监控只产生归因和研究方向报告。
原始论文中的理论性质不等于 OKX 加密永续合约的现实收益。所有案例应区分理论示意 / 论文实验 / 本系统真实 PAPER 事实，不能编造收益率、样本量和成交记录。

## 目录与完整覆盖清单
| ID | 数学理论（原 1–24 清单） | 章节 | 研究性质 |
|---|---|---|---|
| M01 | Itô 引理 | 01 | 随机微积分 |
| M02 | Black–Scholes 方程 | 01 | 衍生品定价 |
| M03 | Heston 随机波动率 | 01 | 随机波动率/期权 |
| M04 | Ornstein–Uhlenbeck | 02 | 均值回归 |
| M05 | GARCH(1,1) | 01 | 条件方差 |
| M06 | Kalman 滤波 | 02 | 状态空间 |
| M07 | 均值–方差优化 | 04 | 组合优化 |
| M08 | CVaR / Expected Shortfall | 04 | 尾部风险 |
| M09 | Kelly 组合优化 | 04 | 对数财富增长 |
| M10 | Almgren–Chriss | 05 | 执行成本 |
| M11 | Hidden Markov Model / Markov Switching | 02 | 概率状态 |
| M12 | HAR-RV | 01 | 多尺度已实现波动率 |
| M13 | OFI | 03 | 订单簿事件 |
| M14 | Hawkes 过程 | 03 | 自激事件流 |
| M15 | CUSUM / Bayesian Change Point | 02 | 在线变点 |
| M16 | XGBoost | 05 | 非线性预测 |
| M17 | VECM / 协整 | 02 | 均衡关系 |
| M18 | DeepLOB | 03 | 深度订单簿建模 |
| M19 | EVT / POT | 04 | 极值统计 |
| M20 | DCC-GARCH | 01 | 动态相关 |
| M21 | CAViaR | 04 | 动态分位风险 |
| M22 | Model Predictive Control / 多期凸优化 | 05 | 多期约束决策 |
| M23 | Queue Imbalance | 03 | 下一跳微观价格 |
| M24 | Deflated Sharpe Ratio | 05 | 多重试验修正 |
另列：White's Reality Check、QLIKE、PIT（point-in-time）审计、Bootstrap、逆向选择/markout，属于研究方法或评价工具，并非另立为 24 项中的新 Alpha 模型。

## 统一理论卡片规则
每个模型至少具备：数学对象；关键公式/符号；基本假设与可识别参数；必要输入和时间频率；统计评价；典型失效与适用性；原始论文。模型可用 != 数据可用 != 代码已实现 != PAPER 证实盈利。
短周期事件模型需真实 L2 增量、源时间戳和缺口验证；日频风险理论不能未经验证直接外推为 1 秒预测。单交易所研究、不包含跨交易所套利。
当已知的真实数据不足、符号含义不明或样本依赖严重时，保留 UNKNOWN/NOT_IDENTIFIABLE，而不是生成参数、论文结论或交易建议。

## 共用研究统计规则（不开展研究）
- 训练与假设选择限定最近 3 个月；更早 3 个月仅为逆时间回溯压力测试，不是顺时间 OOS。真正 OOS 需在选型后积累后续时点数据。
- 记录时点可得的价格、maker/taker 费率、真实合约单位、funding、mark/mid、交易时延、缺失与费用归属。不得把滑点和价差重复计费。
- 数学损失函数 QLIKE、RMSE、log-loss、VaR/ES 违反率、正态性诊断与净收益是不同评价目标；改善预测误差并不必然改善成本后利润。
- 分层对照正确预测但亏损、错误方向、逆向选择、未成交、策略拒绝、缺失数据；拒绝把未成交反事实当成已实现 PnL。
- 三系统中 Lowrisk 与 Quant Core 可比较同一共享策略包/同一 as-of 输入的因子证据，但其 LLM 与确定性决策、资金、交易帐本必须隔离。
- 任何监控输出只能是诊断证据与未来研究方向，不包含可直接应用到交易系统的修改操作。

## 文件
01_STOCHASTIC_VOLATILITY.md：M01/M02/M03/M05/M12/M20。
02_STATE_MEAN_REVERSION.md：M04/M06/M11/M15/M17。
03_MICROSTRUCTURE_EVENTS.md：M13/M14/M18/M23。
04_PORTFOLIO_TAIL_RISK.md：M07/M08/M09/M19/M21。
05_EXECUTION_ML_VALIDATION.md：M10/M16/M22/M24。
06_EVIDENCE_CASES.md：原始/加密实证论文与案例可靠性说明。