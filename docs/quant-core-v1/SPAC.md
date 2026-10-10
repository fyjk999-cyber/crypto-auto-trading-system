# Quant Core V1 — SPAC 项目规格与验收基线

> **状态：工程实施规格（Design Baseline）**  
> 文档版本：`SPAC-V1.0` · 编制日期：2026-10-10  
> 用途：供 Harness / Codex 在用户 Mac 上实施、测试和验收新建 Quant Core；**本文档不是生产部署或 LIVE 授权**。  
> 术语：按用户要求命名 `SPAC.md`；内容采用通常的软件规格说明（SPEC）结构。

## 0. 决策摘要与边界

**目标**：从 Lowrisk 的实际审计版本提取、冻结和复用量化因子计算定义，落地一套**独立运行、全市场动态筛选、无 LLM、确定性交易**的 Quant Core，并向 Lowrisk 提供**相同版本、只读**的量化证据工具。两套系统在**同一 Mac 上使用独立进程、独立 PAPER 账户与资金账本**运行；获授权后才允许独立 LIVE 子账户对照。

**确定的用户选择**：

| 维度 | 决定 |
|---|---|
| 市场 | 现有 OKX 市场数据覆盖内的全市场动态筛选，只有满足可交易性/流动性/风控的标的才进入候选 |
| 基线 | 保留 Lowrisk 原始因子与原策略输出为不可变基线；新策略、改进因子独立作为候选 |
| 模型 | Quant Core 核心**无 LLM 调用、无 LLM 决策依赖**；Lowrisk 保持独立 LLM 决策 |
| 策略一致性 | 同版本策略包/相同哈希/相同输入 => 同因子结果；不同决策引擎允许有不同操作 |
| 行情 | 复用现有 OKX 行情/SharedMarketHistory，禁止部署第二个生产行情采集器 |
| 运行 | 同一机器、独立进程/服务、独立数据库、独立执行 lease、独立日志和实例 ID |
| 账户 | PAPER 使用隔离账户账本；未来 LIVE 必须使用不同交易账户或子账户、分别授权 |
| 演进 | Phase 0 事实审计先行；纯 PAPER 工程门禁通过后才可启动 **新 Quant Core PAPER** |
| 限制 | 不启动/重启/部署当前 Lowrisk；不修改 Lowrisk 生产状态；不执行真实资金交易 |
| 禁止范围 | 跨交易所套利、CEX–DEX 套利、伪造订单簿/成交/标签、未来信息泄漏、未经批准的自动参数晋升 |

**不应被误读的结论**：工程完成≠因子盈利；历史 PAPER 测试通过≠LIVE 可行；Maker 名义手续费低≠Maker 真实总成本低。

---

## 1. 事实基线、证据来源与冲突处理

以下基于用户提供的 **Round 1–4 Harness 回执**和上传的第一轮原始资料。Round 2–4 本地回执尚未由本说明书编写方直接读取源文件，因此描述为**待 Phase 0 在用户机器重新验证的历史报告事实**。不得把本表当作当前进程在线状态。

### 1.1 受审来源与现场

- 受审 Lowrisk SHA：`0697a6da512fb20c570ace40c655705fc4c6cc4d`。
- 历史部署：`~/Library/Application Support/LowRisk/deployments/operational-health-0697a6da`。
- 历史 Round 3 隔离工作树：`/Users/huhongjie/lowrisk-round3-isolated`，分支 `codex/round3-evidence-integrity`；Round 4 报告称补丁仍**未提交、未合并、未部署**。
- 数据源：`/Volumes/My PSSD/SharedMarketHistory`；由既有 canonical writer 写入，Quant Core 只读。
- 历史审计目录：`/Users/huhongjie/lowrisk-factor-audit-v1/`、`round2/v1-20261010T0610Z/`、`round3/v1-20261010T1300Z/`、`round4/v1-20261010T1350Z/`。
- Round 4 回执：Lowrisk PAPER 仍停用；349 订单、438 成交；具体当前状态必须重验；不准 Harness 因发现停机就自动启动。
- `main` 不包含受审 SHA 的报告提示：严禁将 `main` 默认当成生产逻辑的唯一来源。

### 1.2 各轮成果应如何继承

| 来源 | 可以继承的结论 | 必须保留的局限 |
|---|---|---|
| Round 1 | 53 个审计条目；初步五项核心保留：`DET_MOMENTUM`、`X17`、`X22`、`X07`、`X24`；潜在冗余家族 | 当时只有四天有验证标签；分类表、收益期限存在口径问题；不能据此立即重排扫描器 |
| Round 2 | `label-v2` 将标签期限用作源 K 线/对齐基准；离线重建标签扩展到约 24 天；扫描器重排未证实；共识替换不宜晋升 | 24 天仍不足三个月；历史 as-of 可用性、缺失和样本重叠不可忽视 |
| Round 3 | 隔离 `LabelV3Maturer`，63 回归、909/909 目标价；X23 的 `MarketState`→`SymbolFacts` 快照持久化缺陷及 5/5 重放；X21 未训练代理 | 仅新快照可重放；旧记录不能凭空补齐；费用研究曾误判合约乘数 |
| Round 4 | 通过 OKX 公共 SWAP 合约规格独立复算 438/438；合约乘数/名义金额链路一致；模拟器默认费率 10 bps 而其他配置为 5 bps；654/654 全仓测试、106 定向测试报告 | 费率 2/5 bps 是**配置假设**非账户实际费率；逐腿 PnL、资金费、完整权益 replay、Maker 成交概率、容量、净边际仍未验收 |

### 1.3 Round 1 原始附件与纠正

可核对的原始附件：`FACTOR_KEEP_MERGE_DROP_REPORT.md`、`FACTOR_IMPORTANCE_RANKING.csv`。

- 五项 `CORE_KEEP` 包含 **三类 Alpha 候选**（`DET_MOMENTUM`、`X17_SUPPORT_RESISTANCE`、`X22_ORDERBOOK_IMBALANCE`）和**两个非方向控制**（`X07_ATR_NATR`、`X24_MARKET_REGIME`）。
- `X22` 的强统计信号不可等同于成本后可交易信号。
- 最初的“`DET_MOMENTUM` ≥30m 盖过 17bps 成本”措辞错误：30m 毛收益报告为 +15.04bps；且跨 Round 1–4 的样本、期限、成本口径不同，不可直接对比。
- 原有 24 个方向模型并未被证明恰好独立成“四条轴”；Round 2 报告称 PCA/聚类结果更复杂。**不采用强制四轴共识，也不硬编码 Momentum 优先。**
- 已被否定的 Round 3“手续费差异来自合约乘数错误”判断，以 Round 4 的纠正为准。不能再次引入同一误判。

### 1.4 本阶段认定状态

```text
ENGINEERING_BASELINE = TO_REVERIFY_IN_PHASE_0
FACTOR_PROFITABILITY = NOT_VERIFIED
QUANT_CORE_PAPER_READY = NO (until Stage Gate G6)
LOWRISK_PRODUCTION_DEPLOYMENT = NOT_AUTHORIZED
LIVE_EXECUTION = NOT_AUTHORIZED
```

---

## 2. 完整系统边界与部署拓扑

```text
                   Existing OKX Market Services
                   Existing SharedMarketHistory
                           (read only)
                              |
                     Immutable as-of Snapshot
                              |
                Quant Factor Package [version/hash]
                              |
             +----------------+------------------+
             |                                   |
     QUANT CORE PROCESS A                 LOWRISK PROCESS B
     Independent Scanner                  Read-only Factor API/SDK
     Deterministic Strategy               Existing ChiefTrader LLM
     Independent Risk                     Existing Lowrisk Risk
     Independent Execution                Existing Lowrisk Execution
     PAPER Ledger/Account A               PAPER Ledger/Account B
             |                                   |
             +-------------+---------------------+
                           |
             Paired Event/Order/Equity Analysis
```

### 2.1 部署原则

- 一个项目只对应一份主要策略源码定义和一套可发布的版本化接口；可有两个隔离运行实例，**不能人工维护两套越来越不同的因子公式**。
- 同一 Mac 允许复用只读数据源、文件快照和 CPU 计算缓存；不得共用可写订单数据库、资金账本、进程锁、Kill Switch 状态或资金账户。
- 生产数据服务由现有 canonical writer 管理；Quant Core 不拥有采集器启动/写入权限。
- Quant Core 只允许新建 `PAPER` 的自动启动/恢复；Lowrisk 当前服务不属于本任务自动启停范围。
- 调用 Lowrisk 的只读工具应在 API 层与执行层物理隔离；原则上不暴露 `POST order` 等写操作路由。

### 2.2 必需进程（逻辑角色，允许合并部署）

1. `quant-core-paper-runtime`：扫描、确定性决策、风控、PAPER 下单、持仓与对账的唯一写实例。
2. `quant-core-readonly-api`：公开同版本只读因子/信号/健康查询，可独立进程或只读路由。
3. `quant-core-observer`：健康、资源、审计、指标与告警，可随主服务运行。
4. `quant-core-research`：离线实验，不应长期持有实盘授权。

进程名称仅建议，不依赖预设端口。端口按现场审计选择，不能占用 Lowrisk 原 8010 或其他已用端口。

---

## 3. 市场数据契约（硬门禁）

### 3.1 输入来源

- OKX 现有 `SPOT / SWAP / FUTURES` 的可验证公开行情、可交易 instrument 规格；**实际执行交易品类**由本地已验证能力与风险策略确定，V1 优先已支持的线性 SWAP。
- 已有 K 线、成交、盘口、funding、OI、可复现 basis 信息。**不存在的字段不得用代理数据冒充原始数据。**
- SharedMarketHistory 只读；不得采用另一个交易所来补足缺口；不实施跨所套利。

### 3.2 统一记录与质量

每个行情事实最少包含：

```text
source_venue, instrument_id, instrument_type, event_type
exchange_event_time, exchange_publish_time?, receive_time
persisted_at?, decision_available_time, snapshot_id
price_or_value, units, contract_value?, currency?
source_ref, schema_version, data_quality, freshness_ms
```

`?` 表示可缺失但必须显式标 `UNKNOWN`，不能随意假造时间戳；事件可用时点必须以实测采集/持久化事实为依据。历史离线研究不得使用当时尚未采到的数据。

### 3.3 只读历史库的特殊安全条件

- 列举文件时排除 `._*.parquet`、临时文件、未完成 atomic rename 对象；使用可验证的文件清单及哈希。
- 对 SQLite 使用正确的只读一致性 snapshot/backup 机制；不能裸拷贝正在写的主 DB 冒充一致性快照。
- SharedMarketHistory 的短暂可读性失败/校验失败不是“数据为零”；退化为不可用并阻止**新开仓**。
- 冻结研究数据集并附 `sha256 / row_count / min_time / max_time / watermark / source SHA`。
- 历史 1m 区间缺口必须显式暴露；不得仅通过重采历史 K 线推定决策当时就能看到。
- 对旧的 Funding/Basis/OI NULL 快照 `REPLAY_STATUS=UNREPRODUCIBLE`；不历史篡改、不用 0 值填补。

### 3.4 Label-v3

修复标签成熟化应按真正的 **1m 源 bar** 确定对齐边界；验证 1m/5m/15m/30m/1h/4h 期限，保留 v2 兼容与历史可追溯性。训练与标签时点严格隔离，不允许未来函数。

---

## 4. 全市场动态筛选

阶段流：

```text
ALL_MARKET -> OBSERVABLE -> EXECUTABLE -> STRATEGY_ELIGIBLE -> RANKED_CANDIDATES
```

- `ALL_MARKET`：已有 OKX 市场服务能发现的交易合约，保留市场上下架时间。
- `OBSERVABLE`：源数据齐全、快照新鲜、质量达标。
- `EXECUTABLE`：合约规格、交易单位、费率口径、最低数量、点差、深度、风险限制满足门禁。
- `STRATEGY_ELIGIBLE`：该策略支持的市场状态、输入频率和质量条件满足。
- `RANKED_CANDIDATES`：排序有可解释、版本化的评分契约，并保留没有进入 top-k 的候选事实。

保留原 Scanner 为独立基线；**禁止直接启用 Round 1 建议的 Momentum 固定优先顺序**，Round 2 反事实不支持这一改变。新排序校准器默认 `SHADOW_ONLY`，直到新鲜前瞻数据证明有增益。

---

## 5. 因子和策略设计

### 5.1 不可变 Lowrisk Baseline

`LOWRISK_BASELINE_V1` 必须从经审计源 SHA、实际公式、输入口径、参数和归一化中抽取，保存哈希。不可只按项目文档重新实现并声称等价。源公式重用许可/代码所有权依据按实际仓库确认。

### 5.2 第一版核心候选

| 因子/检测器 | 定位 | 状态/实验要求 |
|---|---|---|
| `DET_MOMENTUM` | 动量/机会扫描 | **研究 Alpha**；4h 表现跨样本漂移，不能硬编码优先 |
| `X17_SUPPORT_RESISTANCE` | 价格结构事件 | **研究 Alpha**；独立验证开/平、止损和成本 |
| `X22_ORDERBOOK_IMBALANCE` | 盘口失衡+微价+点差 | **过滤/执行研究**；统计 IC 显著但报告毛 edge 低于成本 |
| `X23_FUNDING_BASIS` | Funding/Basis 方向与拥挤 | **重点候选**；先修持久化与事件可用时点；负 Funding 的历史结果不是交易许可 |
| `X07_ATR_NATR` | 风险、仓位、止损 | **必保留的非方向控制** |
| `X24_MARKET_REGIME` | 市场状态 | **必保留的非方向控制** |
| `X21_ORDER_FLOW_ML` | 未训练代理 | `ENGINEERING_PROXY_NOT_TRAINED`；不能冒充已训练模型或独立 ML 票 |
| `X10_PRICE_OI` | OI/拥挤度 | 方向使用降级候选；保留风险证据，不静默删除 |

其他因子保留 `CORE_KEEP / CONDITIONAL_KEEP / MERGE_MEMBER / CLUSTER_REPRESENTATIVE / RESEARCH_ONLY / INSUFFICIENT_EVIDENCE / RETIRED_CANDIDATE` 等**相互独立的字段**；原报告分类名称与归组应以 Phase 0 重新核对后的规范表为准。

### 5.3 因子记录契约

```text
factor_id, factor_family, semantic_role, source_sha
formula_hash, parameter_hash, factor_version
snapshot_id, input_refs, data_asof, computed_at, expires_at
value, direction?, confidence?, quality, explanation, missing_reason
```

`semantic_role` 分 `ALPHA / REGIME / RISK / EXECUTION / DATA_QUALITY`。`direction_score=0` 的 ATR、Regime 不应参与方向性模型票。

### 5.4 决策策略

- 使用**确定性**市场状态选择、规则触发、信号仲裁、风控审批，再生成订单意图。
- 必须同时保留原规则决策基线与新候选策略；候选策略有 `RESEARCH / SHADOW / PAPER_APPROVED / RETIRED` 四类成熟度，**LIVE 另有独立外部授权**。
- Round 2 证据表示共识去重直接替换效果较差，不强行压缩成四信息轴，更不得把多模型相关当成多个独立投票权。
- 允许 `NO_TRADE` 并使它成为数据或经济优势不足时的正常决策。
- 所有入场与退出均生成可审计的规则版本、输入快照、阈值、预期成本与否决原因。

### 5.5 研究原则

- 最近 3 个月真实可用数据用于策略选择/训练；更早 3 个月作历史稳健性压力测试，**不是“未来样本外”**。
- 如果仅有约 24 天具备时点一致性的标签，必须标记窗口不足；在较短窗口上跑出显著 p 值不可替代后续前瞻 PAPER。
- 使用 purged/embargoed 的时间分割处理持有期标签重叠；报告可用时间簇数和多重检验控制。
- 费后收益、可成交性和收益容量单独报告；不以 `IC × SD` 代理当成实际净 PnL。

---

## 6. 风险引擎（执行不可绕过）

全部 Quant Core 入场、加仓、减仓均由独立风险模块处理；必须覆盖：

- 账户风险预算、单笔止损预算、最大日损失、最大回撤、总敞口、单币敞口、杠杆限制。
- 相关品种敞口合并、极端波动/跳空、异常流动性、价差/滑点上限。
- 无有效价、stale 数据、未知 instrument、未知合约乘数、资金账本不一致 → **禁止新开仓**。
- `KillSwitch` 优先级高于策略方向，紧急停单与安全平仓策略需独立验收；不能在事实未知时盲目反向下单。
- 拒单、重复、未知成交、部分成交、断连、重启必须 fail-closed；未知订单状态先核对事实，再继续执行。
- PAPER 参数应基于保守风险预算并记录 config hash，不能为了自然产生成交而降低限制。

风险边界保证不依赖 Alpha 是否能盈利。

---

## 7. 执行、合约单位、资金账本和费用

### 7.1 成交与单位

交易所 instrument 规则是名义金额与合约张数的权威来源。合约面值按合约类型及计价/结算币种处理，不可假定所有 instrument 都使用同一个单位。

Round 4 已纠正：438/438 按 OKX SWAP instrument 规则复算，原所谓跨数量级手续费异常源于分母遗漏合约乘数；**不能再次把错误结论写入实现**。

### 7.2 费率

- `SimulatedExchangeAdapter` 默认 `Decimal("0.001")` (10bps) 与其他项目配置的 taker `Decimal("0.0005")` (5bps) 不一致；这是隔离补丁中需统一的 bug。
- `maker=0.0002`、`taker=0.0005` 是项目模拟配置，不代表交易所账户费率已核验。
- 使用统一 `FeeSchedule` + 费率来源+适用时间+Maker/Taker；费用计算不应暗中回退到默认旧值。
- 旧账本不改；创建可追溯重述研究账本并明确 `recorded_fee / corrected_fee / assumption / difference`。
- PnL、Cash、Equity、RiskExposure 的单位合同与完整订单生命周期端到端对账。

### 7.3 PAPER 执行器

需要：唯一 writer、幂等 client_order_id、价量精度、reduce-only、市价/限价、撤单/重试、部分成交、未知订单状态、开放持仓恢复、仓位事实对账。独立 PAPER DB 及资产账本，LIVE adapter 默认**不可用于下单**。

### 7.4 订单与资金事件不可逆审计

必需实体：

```text
TradingAccount, TradingSession, MarketSnapshot, SignalEvidence
Decision, RiskApproval, TradePlan, OrderIntent, Order, Fill
Fee, Funding, PositionLeg, Position, CashMovement
PortfolioSnapshot, TradeEpisode, ExecutionReconciliation
```

每个订单绑定：`account_id, strategy_version, source_sha, data_snapshot_id, config_hash, risk_approval_id, client_order_id`。

状态：`INTENT -> APPROVED -> SUBMITTED -> [ACKED/PARTIAL/FILLED/CANCELED/REJECTED/UNKNOWN] -> RECONCILED`；`UNKNOWN` 不得静默视为失败或成功。仓位平仓必须以事实仓位为 0 判定；不以“LLM/策略说退出”作为完成标志。

### 7.5 Maker/Taker/Hybrid 研究

必须分拆手续费、点差、价格冲击、逆向选择、排队成交概率、撤单/重挂、未成交机会损失。已有 L1/L5 快照不能证明真正队列成交；无订单量或队列历史时必须 `MAKER_FILL_MODEL_VERIFIED=NO`。可以进行情景模拟和安全 PAPER 观察，不得声称可实现净 edge。

---

## 8. Lowrisk 只读工具与同版本比较

工具接口（REST + Python SDK；MCP 可选）：

```text
get_market_regime
get_factor_snapshot
get_strategy_signals
get_trade_proposal
explain_signal
get_strategy_performance
get_strategy_health
```

- 工具层不能开放可写订单、调仓、参数改变或账户凭据接口。
- 查询返回 `snapshot_id / factor_version / strategy_version / source_sha / config_hash / asof / expires_at / quality / evidence`。
- 相同输入+配置+因子版本必须 parity，误差要求按类型和数值精度定义；不因两种决策逻辑不同而强行要求两者同仓。
- Lowrisk LLM 仍可独立作 `LONG / SHORT / NO_TRADE / WAIT / HOLD / REDUCE / EXIT` 等决定，由 Lowrisk 原风险和执行控制授权；Quant Core 信号仅是参考。
- 只读工具接入 Lowrisk 的代码可以在**隔离集成工作树**开发和测试；部署到正在运行 Lowrisk、恢复 `com.lowrisk.paper` 需用户单独授权。

---

## 9. 两个独立 PAPER / LIVE 账户的公平比较

### 9.1 三层实验

A：`LOWRISK_ORIGINAL_FACTOR_BASELINE` 与 `QUANT_CORE_FACTOR_CANDIDATE`，只测策略因子改动。  
B：相同量化版本与行情快照，`DETERMINISTIC_DECISION` vs `LOWRISK_LLM_DECISION`，测 LLM 决策增益。  
C：独立 PAPER 账户的实际模拟成交与成本、权益比较，测端到端结果。

### 9.2 配对约束

必须同候选全集、同决策时点、同市场快照、同费率与风险预算、同基准资金（可标准化）、同持有期评价。把 LLM 延迟、调用成本、弃单、选择偏差与执行差异单独归因。B 组可不同方向与仓位，但不能把这些差异再次算成“因子计算差异”。

输出：总净收益、最大回撤、波动率、Sharpe/Sortino（样本充分才计算）、成交成本、成交率、容量、错过机会、LLM 否决/反向/调整仓位的反事实归因、观测窗口、有效样本量和不确定性。

单一收益值不能证明 LLM 因果增益；前瞻试验要求稳定版本及事件配对。

---

## 10. 可观测性、恢复、资源与长期运行

- `health / ready / version / metrics` 检查：源码 SHA、配置 hash、PAPER 模式、账户隔离、数据 freshness、单 writer、kill switch、账本差异、订单 UNKNOWN、磁盘空间。
- 事件日志记录：`cycle_id / run_id / snapshot_id / strategy_version / decision_id / order_id / risk_reason`，不记录凭据。
- 独立 launchd 管理**新 Quant Core PAPER** 时必须确保 KeepAlive 不导致已完成 one-shot 脚本无限重启，不依赖 `/tmp` 持久脚本，稳定环境变量、日志轮转、崩溃恢复，保证幂等启动。
- 遇到源市场 stale、无可验证交易规则、账本对账失败、账户混用，系统应禁止新开仓并上报，不得悄悄绕过。
- 单机资源不足时允许关闭研究计算而保留安全 PAPER；不可为了速度跳过风控/校验。
- 长时间 soak 的“已运行”应有真实 uptime、进程重启次数、真实读数与校验证据；不得只凭测试通过声称运行成功。

---

## 11. 逻辑项目目录

```text
quant-core/
├── SPAC.md                          # 本文档
├── GOAL.md                          # Harness 主目标
├── config/{universe,factors,strategies,risk,execution,experiments}/
├── src/quant_core/
│   ├── data/{adapters,snapshots,shared_history,quality}/
│   ├── universe/{instruments,eligibility,liquidity,ranking}/
│   ├── factors/{baseline,momentum,support_resistance,orderbook,funding_basis,volatility,regime}/
│   ├── strategies/{registry,baseline,candidates,arbitration}/
│   ├── decision/{deterministic_engine,trade_proposal,evidence}/
│   ├── risk/{position_sizing,exposure,drawdown,kill_switch}/
│   ├── execution/{paper,live_adapter,orders,fills,reconciliation}/
│   ├── portfolio/{ledger,positions,cash,valuation}/
│   ├── integration/{api,sdk,lowrisk,contracts}/
│   ├── research/{replay,backtest,cost_model,experiments}/
│   └── operations/{health,supervision,telemetry,recovery}/
├── tests/{unit,integration,property,replay,parity,safety,soak}/
├── scripts/
└── docs/{decisions,contracts,receipts,runbooks}/
```

目录为功能边界；允许通过现有可复用实现简化结构，禁止只创建空目录便宣称完成。

---

## 12. 完整实施计划和阶段门禁

| 阶段 | 必交付可验收能力 | 门禁/阻塞 |
|---|---|---|
| P0 现状审计 | 当前 Lowrisk 部署、源码 SHA、研究补丁、数据源、进程与权限清单 | 无真实 SHA/工作树状态，不得实施可能污染已有仓库的操作 |
| P1 会计基础 | fee schedule、合约单位 fail-closed、完整 PAPER 开→减→平→权益测试、438 历史成交独立研究重述 | 手续费/名义金额/权益无法一致复算 => 禁止 PAPER 启动 |
| P2 证据链 | Label-v3、Funding/Basis/OI、X21 代理标记、as-of、历史库一致性读 | 不能做时点校验的数据不进入信号 |
| P3 独立项目 | 单机进程隔离、策略包版本化、动态 universe、因子/扫描基线 parity | 跨账户或跨进程写状态 => 禁止 PAPER |
| P4 决策风控 | NO_TRADE、入/出场、仓位 sizing、风险门禁、Kill Switch、订单授权 | 发现任何绕开风险的执行路径 => 阻塞 |
| P5 PAPER 执行 | 订单幂等、成交账本、恢复对账、故障注入、对不同合约规格的核算 | UNKNOWN 状态误处理、单 writer 失败、数据 stale => 阻塞 |
| P6 独立 PAPER | 仅新 Quant Core 在 PAPER 模式启动、健康、日志、完整工程 smoke、持续 soak | 只有全部安全门禁 PASS 才允许启动；自然交易不足需标 PENDING |
| P7 Lowrisk 接入 | 只读 API/SDK、同版本因子 parity、Lowrisk 隔离集成候选 | 不能擅自部署、启动 Lowrisk；需要用户授权则记外部 blocker |
| P8 实验 | 因子对照、LLM 决策反事实、独立账本成本/风险配对 | Lowrisk 停用时只能交付实验基础与可离线结果，不能虚构在线 A/B |
| P9 策略研究 | 最近 3 个月的真实可用数据验证、前瞻观测、Maker/Taker/Hybrid 研究 | 数据不足/成本不清则 `EDGE_NOT_VERIFIED`，但工程可独立完成 |
| P10 运营就绪 | 可恢复长时间 PAPER、分离配置与审计回执、独立运行手册 | 资源不足、采集不可用时 fail-closed |
| P11 LIVE 准入 | 设计独立账户授权流程、账户费率核验、资金/限额验收清单 | 本目标内绝不激活真实下单；必须用户新授权 |

阶段可以在不破坏依赖关系前提下并行；不能因为学术回测缺少三个月而跳过执行和安全测试，也不能因为工程完成而宣布策略盈利。

### 12.1 关键硬门禁（满足后才可启动**新 Quant Core PAPER**）

```text
G0_SOURCE_SHA_TRACED                 = PASS
G1_LOW_RISK_PRODUCTION_UNCHANGED      = PASS
G2_DATA_SOURCE_READONLY_AND_FRESH     = PASS
G3_CONTRACT_UNITS_AND_FEES_CORRECT    = PASS
G4_LEDGER_RISK_ORDER_RECOVERY         = PASS
G5_MODE_PAPER_AND_LIVE_DISCONNECTED   = PASS
G6_ACCOUNT_LEASE_PROCESS_ISOLATION    = PASS
G7_TEST_SUITE_AND_SMOKE               = PASS
G8_KILL_SWITCH_AND_FAIL_CLOSED        = PASS
```

若任一门禁未通过，**不要启动可自主产生订单的 PAPER 实例**；可以执行纯离线 Replay/Shadow 验证并报告原因。

### 12.2 端到端最低验收矩阵

- 在确定性测试数据下完成：下单→成交→减仓→平仓→费用→权益→交易事实日志；测试不等于自然成交事实。
- 多 instrument / 特殊 ctVal 合约单位与费率复算，明确 10bps 历史错误更正的适用范围。
- 新旧版 label 数值 parity、Funding 快照 replay parity、NULL 失败行为。
- 同 SHA/配置/快照下 Quant API 和 Lowrisk SDK 的因子输出一致。
- Kill Switch、未识别合约、断连、重复提交、部分成交、UNKNOWN、磁盘空间不足、DB 只读/损坏的故障注入。
- 稳定运行观测：uptime、重启、订单事实、风险拒绝、数据时延、权益对账。
- 较长时间没有真实自然成交时明确标记 `NATURAL_EPISODE_PENDING`，不可强造交易通过验收。

---

## 13. 代码、研究报告与发布约束

- 先读实际代码后改动；按每阶段单独 commit、记录源 SHA 和测试，不整理或清理用户已有 dirty 文件。
- Round 3/4 未提交补丁须先 diff 与隔离复核，不可直接 cherry-pick 不明范围变更或篡改原提交。
- 已否定的因子替换默认关闭：**强制四轴共识、无验证 Momentum 固定置顶、把 X21 代理算成训练 ML、把旧 X23 NULL 当有效零值**。
- 禁止将原仓库默认 `main` 覆盖为生产策略。不得 force push。若仅开发于新隔离分支，可本地 commit；推送远端新分支应服从仓库已有授权规范，不能自动合并或部署。
- 所有未完成的外部依赖明确列 `BLOCKED_BY_USER_AUTH / NOT_VERIFIED / NOT_APPLICABLE`，不要请求用户重复提供已在项目中可审计的信息。
- 每一阶段产出：代码/哈希、变更清单、测试日志、独立 reviewer 结果、实际阻塞项、下一自动任务。

### 13.1 最终交付清单

```text
QUANT_CORE_SOURCE_SHA
QUANT_CORE_BRANCH
LOWRISK_BASELINE_SHA
DATA_CONTRACT_HASH
FACTOR_REGISTRY_VERSION
STRATEGY_CONFIG_HASH
UNIT_ACCOUNTING_RECEIPT
LABEL_V3_PARITY_RECEIPT
SNAPSHOT_PROVENANCE_RECEIPT
PAPER_EXECUTION_E2E_RECEIPT
PAPER_PROCESS_ISOLATION_RECEIPT
LOWRISK_READONLY_FACTOR_PARITY_RECEIPT
MARKET_UNIVERSE_COVERAGE_REPORT
PAPER_RUNTIME_HEALTH_AND_SOAK_RECEIPT
PAIRWISE_EXPERIMENT_REPORT_OR_BLOCKER
LIVE_READINESS_REPORT_ONLY
```

最终状态需分别报告：`ENGINEERING_READY / DATA_READY / PAPER_SAFE / PAPER_RUNNING / STRATEGY_EDGE_VERIFIED / DUAL_SYSTEM_PARITY / LIVE_READY / PRODUCTION_MODIFIED / REAL_ORDERS`。

**完成条件**：在本目标的授权范围内，新 Quant Core 可在安全的独立 PAPER 环境实现端到端自主交易；Lowrisk 只读工具与因子版本 parity 在隔离测试通过；工程证据可重放，生产未改动。历史三个月不足、Maker 队列不可验证和 Lowrisk 尚未恢复，可使盈利、在线 A/B、LIVE 仍为 `NOT_VERIFIED`，不应伪装为完整商业化上线。

---

## 14. 不可擅自跨越的最后授权界线

```text
QUANT_CORE_NEW_PAPER = ALLOWED_AFTER_ALL_SAFETY_GATES_PASS
LOWRISK_PRODUCTION_MODIFICATION = FORBIDDEN_WITHOUT_NEW_USER_APPROVAL
LOWRISK_RESTART = FORBIDDEN_WITHOUT_NEW_USER_APPROVAL
LIVE_EXCHANGE_ORDER = FORBIDDEN_WITHOUT_NEW_USER_APPROVAL
LIVE_ACCOUNT_CREDENTIAL_ACCESS = FORBIDDEN_WITHOUT_NEW_USER_APPROVAL
FUNDS_TRANSFER = FORBIDDEN_WITHOUT_NEW_USER_APPROVAL
```

此规范随新审计事实按版本变更，不应静默改写历史版本。发生与 Round 1–4 报告冲突的实证，以**当前真实代码、运行时与可靠测试事实**为准，另写勘误说明。