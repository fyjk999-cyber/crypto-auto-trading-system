# GOAL — 交给 Harness 的可执行主指令

你是这个工程的总负责 Agent（量化架构、交易执行、风险、数据、集成、测试、独立验收），请在**用户 Mac 本地环境**把 `SPAC.md` 规定的 Quant Core V1 从现有 Lowrisk Round 4 审计基础**真正实现到安全的独立 PAPER 运行**。

## 最高优先级与文档定位

1. **首先读取同目录 `SPAC.md` 全文。** 此文件是功能、因子、架构、数据、风险、执行、验收、阶段及权限的唯一正式范围基线。本 GOAL 是执行驱动而非替代 SPAC。文件如尚未放到本机，请检查当前项目/用户提供路径；无法找到 SPAC 则只能做环境审计和定位，**不得自行猜测规格后动生产**。
2. 先核查受审 Lowrisk 代码 SHA `0697a6da512fb20c570ace40c655705fc4c6cc4d`、实际部署根目录、Round 3/4 研究与隔离补丁、Git dirty 状态、SharedMarketHistory 只读源、launchd 与数据服务。历史路径只是定位线索，当前真实事实优先。
3. **不要只写文档或计划。** 按 SPAC P0–P11 逐阶段编写实际代码、测试、校验、重放、运行新 Quant Core PAPER；能安全自动继续的任务不必每阶段再问。不可做的步骤按证据标记 blocker，继续其他独立任务。

## 必须完成的顺序

- **P0 基线与隔离**：确认 Lowrisk 受审 SHA（不能默认 `main`）、识别 Round 3/4 未提交补丁；创建 Quant Core 独立仓库/隔离工作树、Python 环境、数据库、配置、日志及 PAPER account/lease；不清理用户已有 dirty 路径。
- **P1 资金金额与费用**：保留 Round 4 关于合约乘数正确的结论，核对 OKX 合约类型及 `ctVal`；在隔离实现中修复 `SimulatedExchangeAdapter` 10bps 默认与项目 5bps 配置不一致，统一版本化费率表；绝不将 2/5bps 配置冒充当前 OKX 账户费率。建立完整订单→部分成交→减仓→平仓→Fees→Cash→Equity 端到端测试，对历史 438 fills 的更正只生成独立研究账本，不覆盖原记录；未知 instrument 必须 fail-closed。
- **P2 时点数据**：隔离整合 Label-v3 的 1m bar 对齐及 Funding/Basis/OI 快照时间戳/来源持久化，保留旧版本与 NULL 兼容；X21 保持 `ENGINEERING_PROXY_NOT_TRAINED`，不能当作有训练产物的 ML 投票；SharedMarketHistory 仅只读，支持文件冻结、校验、临时文件过滤、SQLite 一致性快照及数据 freshness fail-closed。
- **P3 全市场与因子**：复用已有 OKX 行情服务，禁止重复采集；动态筛选 ALL_MARKET→OBSERVABLE→EXECUTABLE→STRATEGY_ELIGIBLE→RANKED；保留 Lowrisk 原始因子/Scanner/Consensus 版本哈希作为 immutable baseline；实现 Momentum、Support/Resistance、X22、Funding/Basis、ATR、Regime 等经审计模块，其他作为独立研究或 Lowrisk LLM 参考。不要强制“四信息轴”，也不要未经前瞻证明就简单将 Momentum 置顶。
- **P4 确定性决策与风控**：不调用 LLM；实现 NO_TRADE/LONG/SHORT/HOLD/REDUCE/EXIT，规则可复现；波动率仓位、风险限额、数据质量、费率/滑点、Kill Switch、仓位与账户敞口不可绕过；信号预期优势未知时允许 NO_TRADE。
- **P5 执行及账本**：建立单 writer、幂等订单、部分成交、撤单、超时、UNKNOWN 状态恢复、合约单位和资金对账、持仓与 TradeEpisode 状态；安全 PAPER 适配器与 LIVE 硬隔离。Maker/Taker/Hybrid 可做研究接口，但没有队列证据不可宣称 maker 成交率、容量或费后盈利已验证。
- **P6 PAPER**：仅当 SPAC G0–G8 安全门禁全部 PASS，才启动**新建 Quant Core 独立 PAPER**；同一台 Mac 与 Lowrisk 独立进程、端口、账本、租约、配置和日志。完成真实健康检查、smoke、崩溃恢复和持续观测；禁止以降低阈值强造自然交易。如果门禁不通过，则保持纯 shadow/replay 并报告真实原因。
- **P7 Lowrisk 接入**：实现同版本量化内核的 REST+Python SDK 只读 API（regime、factors、strategy signals、trade proposal、explanation、performance、health）；对同快照/同配置的因子结果做 parity；Lowrisk LLM 保留独立方向、仓位、退出决策与原风控。Lowrisk 接入补丁只在隔离工作树测试；**不得擅自启动、改动或部署 Lowrisk**。
- **P8–P10 实验与运营**：建立原始基线 vs Quant 候选、规则决策 vs LLM、独立 PAPER 账本三类对照；前瞻数据和真实成本优先，最近三个月不足则如实标记；完成运行观察、恢复手册、数据与研究可重放报告。Lowrisk 未上线时不能假装在线 A/B 已执行。
- **P11 LIVE 准入**：只生成 LIVE 接口硬隔离、独立子账户安全、真实费率核验与人工批准的验收清单；**不得连接真实下单凭据或启用 LIVE**。

## 明确的负面约束

```text
NO_PRODUCTION_LOWRISK_CHANGE
NO_LOWRISK_RESTART
NO_EXISTING_LEDGER_OVERWRITE
NO_SHARED_MARKET_HISTORY_WRITES
NO_DUPLICATE_MARKET_COLLECTOR
NO_LLM_PROVIDER_CALL_FOR_QUANT_DECISION
NO_LIVE_ORDER
NO_FUNDS_TRANSFER
NO_FORCE_PUSH_OR_MAIN_OVERWRITE
NO_UNVERIFIED_STRATEGY_AUTO_PROMOTION
```

本 GOAL **只批准新 Quant Core 安全门禁通过后的 PAPER 运行**。不隐含授权修改 Lowrisk、恢复旧 PAPER、连接真实账户或者交易真实资金。若下一步必须越界，保留成果并准确报告 `USER_AUTH_REQUIRED`，不要擅自执行。

## 自主执行与验收循环

每阶段按以下闭环进行：

```text
INSPECT_ACTUAL_STATE
-> DEFINE_CONTRACT_AND_TESTS
-> IMPLEMENT_IN_ISOLATION
-> TARGETED_TESTS
-> REGRESSION_TESTS
-> INTEGRATION_AND_REPLAY
-> INDEPENDENT_CRITICAL_REVIEW
-> DOCUMENT_EVIDENCE
-> LOCAL_COMMIT_ON_ISOLATED_BRANCH
-> NEXT_AUTOMATIC_PHASE
```

- 真正的阻塞只阻塞相关阶段，不能因三个月数据不足而停止非盈利证明的安全工程实现。
- 若测试失败，定位根因并修复，不能跳过测试或改假定值；重新跑目标测试与回归。
- 不重新推翻 Round 4 已证明的合约单位事实，除非拿到新的可验证事实且出具修正报告。
- 版本、测试、数据哈希全部可复现；开发分支可本地提交，未经确认不得 force push、合并到生产分支或部署。
- 最终不存在需要自动执行却被写成“下一步建议”的剩余工作；未完成原因必须具体、可定位。

## 最终交付与回执

提交项目源码（在 Mac 本地独立目录）、测试、配置样本（不含凭据）、操作手册、完整审计与兼容性报告、版本化因子契约、独立 PAPER 运行回执、Lowrisk 只读 parity 回执、净收益/成本研究局限与 LIVE 准入清单。

最终报告必须包含：

```text
# QUANT CORE V1 — FINAL ENGINEERING RECEIPT
SPEC_VERSION = SPAC-V1.0
LOWRISK_BASE_SHA =
QUANT_CORE_BRANCH =
QUANT_CORE_SOURCE_SHA =
QUANT_CORE_WORKTREE =
SOURCE_AND_CONFIG_HASH_MATCH =
MARKET_DATA_SOURCE_AND_READONLY =
DYNAMIC_UNIVERSE_COVERAGE =
FACTOR_BASELINE_PARITY =
LABEL_V3_PARITY =
FUNDING_SNAPSHOT_PARITY =
X21_PROXY_IDENTITY =
CONTRACT_UNIT_AND_FEE_CLOSURE =
PAPER_LEDGER_E2E =
RISK_FAIL_CLOSED =
KILL_SWITCH_AND_RECOVERY =
TEST_RESULTS =
READONLY_API_PARITY =
PROCESS_AND_ACCOUNT_ISOLATION =
PAPER_GATES_G0_TO_G8 =
QUANT_CORE_PAPER_RUNNING =
PAPER_RUNTIME_SOURCE_SHA =
PAPER_SOAK_EVIDENCE =
LOWRISK_ONLINE_AB_STATUS =
FACTOR_NET_EDGE_VERIFIED =
MAKER_FILL_AND_CAPACITY_VERIFIED =
PRODUCTION_LOWRISK_MODIFIED = NO
LOWRISK_RESTARTED_BY_TASK = NO
LIVE_ORDERS = 0
LIVE_ENABLED = NO
BLOCKERS_WITH_EVIDENCE =
FINAL_PROJECT_STATUS = COMPLETE / PARTIAL / BLOCKED
```

**完整工程验收与策略盈利认证必须分开。** `COMPLETE` 表示本 GOAL 授权范围内工程和安全 PAPER 验收完成；不代表已证明策略长期盈利或 LIVE 已获授权。历史时点数据不足、Maker 排队未验证、Lowrisk 尚未获准重启时必须按事实输出 `NOT_VERIFIED / PENDING / USER_AUTH_REQUIRED`。

**现在开始执行 Phase 0；完成所有安全且可执行的阶段后再提交最终回执。不要用规划文档代替实际实现。**