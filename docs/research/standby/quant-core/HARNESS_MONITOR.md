# QUANT CORE V1 — 12 小时 PAPER 确定性策略归因监控 V2（REPORT-ONLY）
北京时间 Asia/Shanghai 每日固定 00:00 / 12:00，分别覆盖刚结束的完整 12h；报告之外完全只读。

## 两层独立知识库
全量 24 项理论：docs/research/model-library/v2/00_INDEX.md 及 01–06 理论专题。
本系统聚焦模型理论：docs/research/standby/quant-core/MODEL_KB.md（V2），重点是共享因子、确定性规则、费用、市场状态与尾部风险。
全量理论不自动转为可部署模型；系统聚焦理论不是预写优化方案。忽略旧 V1 中任何类似“优先实施阶段”的结构。

## 每次只读观察
1. 仅识别当前 Quant Core **真实本机**运行 SHA、进程与 PAPER 账户；过去工程 G0–G8 PASS 和 GitHub 文档 SHA 不能代替运行事实。STOPPED 时禁止启动。
2. 对现有订单/账本事实区分 candidate、deterministic decision、RiskDecision、ACK/fill、no-fill、episode、gross/net、真实 fee/funding/slippage、ctVal/资金变动；数据质量缺陷标为 BLOCKED，不推断 Alpha 已失效。
3. 对比盈利和未盈利的实际闭仓订单、拒绝/未成交等事件；窗口 12h、滚动 7d/30d，保留样本数、依赖性和源时间戳。
4. 共享策略 parity **只读**：与 Lowrisk 的 strategy_package_hash、feature_version、as-of snapshot_hash 以及因子/candidate hash 完全匹配的情形才可比较；否则 NOT_COMPARABLE。确定性规则与 LLM 最终决策不同不代表因子错误；账本绝不能合并。
5. 引用 QUANT_CORE V2 重点理论和统一 24 项理论对亏损作竞争解释。证据不支持时不提出特定模型。
6. 每窗口最多输出一个 MAIN_THEORY_TOPIC 与两个 OTHER_POSSIBILITIES，附学术 DOI、对应事实、反例、必要但缺失的观察指标；不得提供具体优化方案。

## 固定报告字段
QUANT_CORE_MODEL_WATCH_REPORT_ONLY；
北京时间窗口与当前源码 SHA、账户；
NET_PNL_RECONCILIATION、CLOSED_EPISODES_COUNT、WIN_VS_LOSS_COMPARISON、FEES/FUNDING；
FACTOR_PARITY_AND_INPUT_MATCH、DETERMINISTIC_VS_LLM_DECISION_DIFF；
DATA_AND_ACCOUNTING_BLOCKERS、SUPPORTING_FACTS、ALTERNATIVE_EXPLANATIONS；
LITERATURE_AND_THEORETICAL_RESEARCH_DIRECTION；
NO_ACTION_TAKEN=YES。
单独输出到 ~/AI-Monitor-Reports/quant-core/，仅新建不覆盖 Markdown/JSON 文件；报告不写到交易工作树和共享历史目录。

## 不可逾越的权限边界
周期执行者禁止修改任何运行时、策略包、因子、订单、风险、交易账户、数据/服务、Git、KB 或其他监控任务；禁止训练、回测、模拟成交、Shadow、重启/停机/下单/撤单/调杠杆。报告中的“方向”只能是“哪个数学解释值得未来研究”，禁止参数、代码、策略替换、实施次序及自动执行。
一次性配置可安装独立只读监控调度与报告存储，但不能触碰现有 Quant Core / Lowrisk / Turbo 交易进程、lease、launchd ownership 或行情 writer。验证 Asia/Shanghai 固定钟点，不允许不安全的重叠执行；不能隔离权限则 MONITOR_SECURITY_FAIL 并保持未安装。
