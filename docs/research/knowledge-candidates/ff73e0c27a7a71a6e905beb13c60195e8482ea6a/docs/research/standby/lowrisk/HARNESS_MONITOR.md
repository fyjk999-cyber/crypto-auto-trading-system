# LOWRISK — 12 小时 PAPER 盈亏归因监控契约 V2（REPORT-ONLY）
**Asia/Shanghai：每天 00:00 / 12:00 的日历时间窗口；仅输出报告。**

## 知识库必须读取的两个独立层级
1. 全量数学理论（24 项）：docs/research/model-library/v2/00_INDEX.md，以及 01–06 的理论和文献分卷。它是理论参考，不是候选实施清单。
2. 系统重点理论：docs/research/standby/lowrisk/MODEL_KB.md（V2），说明 Lowrisk 特有因子、LLM/Quant Core 共享策略关系、未盈利事件的理论解释地图。
不能将旧版 MODEL_KB V1 候选表的优先阶段当作执行命令；V2 生效时以当前文档为准。

## 唯一任务：已有 PAPER 事实的只读解释
每次读取之前完整 12 小时窗口 [上个整点边界,当前整点边界)，并对照 7d/30d 的真实已存在资料；读取实际 Lowrisk runtime SHA、PAPER account、strategy_package_hash、LLM decisions、factor snapshots、risk、orders、fills、funding/fees、真实净损益。保留盈利样本、未盈利样本、no-fill/no-trade 与数据缺口。
只读比对 Quant Core：必须同共享策略哈希、as-of 输入与特征版本；最终 LLM 与 deterministic 决策允许不同，不合并账本，不要求对方启动。
首先区分：数据/合约单位/费用/账本问题；方向预测问题；市场状态解释不足；真实成交问题；风险和 LLM 差异。若缺少证据，则输出 UNKNOWN / NOT_COMPARABLE / INSUFFICIENT_EVIDENCE。

## 报告内容（不含处方）
- 窗口与实际 runtime SHA / PAPER 状态 / 数据来源，含 STOPPED 时的限制。
- PnL：已实现、未实现、外部现金流区分，gross/net/fees/funding/slippage 对账；n 个真实闭仓 episodes。
- 观察：哪些交易没有产生净利润、同时哪些交易盈利、订单生命周期或方向/价格关系。
- 理论解释：每一个原因给出 SUPPORTING_FACTS / ALTERNATIVE_EXPLANATIONS / CONTRADICTING_FACTS / MISSING_EVIDENCE，谨慎使用“可能”。
- 研究方向：可标注 1 个最相关 THEORY_TOPIC、最多 2 个 SECONDARY_TOPICS，引用 V2 理论章节及至少 1 篇真实论文，不给交易修改步骤。
- 若与 Quant Core 可比：FACTOR_PARITY 与 DECISION_DIVERGENCE，若不可比则说明缺少的版本或行情证据。
- RECEIPT：LOWRISK_MODEL_WATCH_REPORT_ONLY，NO_ACTION_TAKEN=YES，附 12h 窗口、源哈希与报告路径。

## 严禁事项
周期任务对三套交易系统、知识库、代码、Git、运行 DB/资金/行情、策略包、服务与进程完全只读。禁止启动/恢复/停止 PAPER；下单/撤单/平仓；修改因子、LLM Prompt、参数、风险、策略、仓位、杠杆；下载执行脚本；自动训练、回测、Shadow、A/B 或晋升；修改知识库自身；读取或输出凭据。
**尤其禁止根据理论索引预先生成具体优化方案**（参数数值、阈值、策略替换、代码实现顺序、部署流程）。只能根据损失事实形成理论解释与未来研究主题。
唯一允许周期性业务写入为新建不可覆盖 Markdown/JSON 报告到 ~/AI-Monitor-Reports/lowrisk/；无安全隔离写目录则仅回传 FAIL_CLOSED 状态。

## 调度与部署权限
只允许一次性建立**监控自身**的隔离定时调度与报告目录，不允许触碰现存交易服务/launchd labels/历史数据 writer。使用真实时区感知调度验证北京时间 00:00 与 12:00（如果 Mac 非中国时区不能假定本地 cron 是北京时间）；避免窗口重叠与重跑重复写文件。权限无法安全隔离就不安装。
最近三个月是未来研究假设选择窗口，较早三个月是逆时间压力参考，不可报告为独立前向测试；监控自己不执行历史模型研究。
