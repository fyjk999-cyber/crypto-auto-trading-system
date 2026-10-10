# 随机过程、波动率与动态相关理论（M01 / M02 / M03 / M05 / M12 / M20）
知识材料；不构成策略或执行配置。符号：S 为资产价格、r 为收益、W 为布朗运动、h 为条件方差、RV 为已实现方差。

## M01 Itô 引理（理论工具）
**对象**：连续时间随机过程的函数变化。若 dX_t = μ_t dt + σ_t dW_t，二阶连续可微函数 f(t,X_t) 满足
$$df=(f_t+\mu f_x+\tfrac12\sigma^2 f_{xx})dt+\sigma f_x dW.$$
对 GBM 形式 dS/S = μdt+σdW，得到 d log S = (μ−σ²/2)dt+σdW。二次变差导致修正项，不能直接按普通链式法则计算。
**假设及局限**：过程满足相应 Itô 可积性/光滑性；真实价格有跳跃、撮合离散性、交易成本，连续扩散近似不一定成立；跳跃过程需扩展 Itô 公式。**数据**：连续时间近似的价格/方差，不是独立买卖信号。**理论案例**：对数价格的漂移修正，可用来理解期权、扩散假设和风险估计。**原始文献**：Itô (1944), Stochastic Integral, DOI 10.3792/pia/1195572786。

## M02 Black–Scholes–Merton 方程（衍生品定价）
在无套利、理想连续复制和常数波动率等条件下，欧式期权价值 V(S,t) 满足
$$\frac{\partial V}{\partial t}+\tfrac12\sigma^2S^2\frac{\partial^2 V}{\partial S^2}+rS\frac{\partial V}{\partial S}-rV=0.$$
**理论**：通过 Delta 对冲消除扩散风险，风险中性定价而非直接预测资产真实上涨概率。**假设**：连续交易、流动性、融资与卖空等理想化条件；实际跳跃、微笑、交易成本和期权机制导致偏离。**参数/数据**：期权行权价、期限、标的、无风险利率、波动率/隐含波动率。**案例**：欧式看涨期权理论价格与隐含波动率比较；对单独永续合约方向预测没有直接含义。**文献**：Black & Scholes (1973), The Pricing of Options and Corporate Liabilities, DOI 10.1086/260062；Merton (1973), Theory of Rational Option Pricing, DOI 10.2307/3003143。

## M03 Heston（平方根随机波动率）
$$dS_t=\mu S_tdt+\sqrt{v_t}S_tdW^S_t,\qquad dv_t=\kappa(\theta-v_t)dt+\xi\sqrt{v_t}\,dW^v_t,\quad d\langle W^S,W^v\rangle_t=\rho dt.$$
v 为瞬时方差；κ 回复速度、θ 长期方差、ξ vol-of-vol、ρ 相关性。常用 Feller 条件 2κθ≥ξ² 可减少方差碰到 0 的情形，但并非在所有应用中都是模型存在性的必要条件。
**估计**：通过期权价格/隐含波动率曲面校准；单纯永续 K 线很难识别完整期权风险中性参数。**案例**：解释期权波动率偏斜和随机波动率期限效应，而非秒级方向决策。**失效**：参数不稳定、校准不可识别、跳跃、模型误定。**原文**：Heston (1993), A Closed-Form Solution for Options with Stochastic Volatility, DOI 10.1093/rfs/6.2.327。

## M05 GARCH(1,1)（条件方差）
$$r_t=\mu_t+\epsilon_t,\ \epsilon_t=\sqrt{h_t}z_t,\ \ h_t=\omega+\alpha\epsilon_{t-1}^2+\beta h_{t-1}.$$
z_t 常取零均值单位方差扰动；正方差标准约束 ω>0、α≥0、β≥0，α+β<1 保证常见弱平稳情形下有限无条件方差，E[h]=ω/(1−α−β)；该条件不是所有扩展模型的必要条件。可选正态/Student-t 误差分布；通过极大似然或拟似然估计。
**评估**：下一期及多期条件方差预测，QLIKE / RMSE、VaR 覆盖、残差 ARCH；条件方差 ≠ 收益方向和盈利概率。**风险**：高频微观噪声、结构突变、样本不足、参数接近 IGARCH、正态尾部偏差。**案例**：对 Bitcoin 波动聚集进行条件方差估计，须与 ATR/NATR、EWMA、HAR-RV 同口径比较。**论文**：Bollerslev (1986), Generalized Autoregressive Conditional Heteroskedasticity, DOI 10.1016/0304-4076(86)90063-1；Katsiampa (2017), Volatility estimation for Bitcoin, DOI 10.1016/j.econlet.2017.08.023。

## M12 HAR-RV（多时间尺度的已实现方差）
若日内收益 r_{t,j}，可定义 RV_t=Σ_j r²_{t,j}；日、周、月组合为 RV^d、RV^w、RV^m。典型式：
$$RV_{t+1}=\beta_0+\beta_dRV^d_t+\beta_wRV^w_t+\beta_mRV^m_t+\varepsilon_{t+1}.$$
**理论**：以多尺度线性组件近似波动率长记忆，并非声称其严格具有真正长记忆。**估计**：常用 OLS、稳健损失/正值变换；需要足够历史、明确采样和日历定义。**数据风险**：交易所 24/7、采样噪声、断连、漏 K 线、不同 K 线窗口重叠。**案例**：多尺度波动率预测，不等于交易信号，不能把分钟级预测套用日周月论文结论。**论文**：Corsi (2009), A Simple Approximate Long-Memory Model of Realized Volatility, DOI 10.1093/jjfinec/nbp001。

## M20 DCC-GARCH（动态条件相关）
对多资产收益残差建立各自条件波动率 h_{i,t}，标准化 u_t=D_t^{-1}\epsilon_t；相关中间矩阵
$$Q_t=(1-a-b)\bar Q+a u_{t-1}u_{t-1}^\top+bQ_{t-1},\quad R_t=\operatorname{diag}(Q_t)^{-1/2}Q_t\operatorname{diag}(Q_t)^{-1/2}.$$
总协方差 H_t=D_tR_tD_t，需相关参数约束以保持合适性质。
**理论**：随时间变化的协方差/相关暴露，不是独立 Alpha；参数估计不稳定、市场危机期间尾部相关可能不由简单线性相关捕获。**数据**：同步的多资产收益与对齐交易时区；不能将停牌/断连后前向填充的数据视为真实独立观测。**案例**：观察多个币种在波动时的共同方向风险。**文献**：Engle (2002), Dynamic Conditional Correlation, DOI 10.1198/073500102288618487。

## 共同理论边界
波动率模型解释/预测风险，并不能直接预测价格符号；期权定价模型并非永续合约方向模型。样本窗口最近 3 个月约束下，不允许虚构 HAR 长窗数据或 Heston 期权曲面。