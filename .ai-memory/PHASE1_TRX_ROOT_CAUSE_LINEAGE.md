# PHASE 1 证据包 — TRX 快速反向操作根因 (TERRA/CODEX 2026-08-30)
**编制**: 独立证据方 (Claude) | **数据源**: data/crypto_trader.db (唯一事实来源) | **用途**: Codex PHASE 1 PASS 审定参考
**状态**: 校准已冻结 (OBSERVE/HOLD gate, staged 300 已回滚至 240); 本文档仅含事实与 lineage,不含代码变更

---

## 一、异常周期完整 DB Lineage (TRXUSDT, 2026-08-30 00:40:06 → 00:46:53)

### 事件分类总表 (ENTRY / EXIT / REDUCE / REVERSAL)

| # | 时间 (UTC) | 事件 | 分类 | Actor (strategy_id) | position_side / reduce_only | 价格 | 数量 |
|---|---|---|---|---|---|---|---|
| 0 | 08-29 20:40:02 | BUY (入场,前置) | **ENTRY** | llm_chief_trader | FLAT / 0 | 0.3396 | 0.001 |
| 1 | 00:40:06.016→08.349 | SELL FILLED | **EXIT** (4h TIME_STOP, 持仓 14405.6s) | ai_brain | LONG / **1** | 0.34067 | 0.001 |
| 2 | 00:40:42.773 | Decision LONG | ENTRY 决策 | llm_chief_trader | — | — | — |
| 2a | 00:40:42.770 | LLM 调用 (live_analysis, deepseek-chat) | — | — | — | — | — |
| 2b | 00:40:43.871 | Order ord_e3771ddad144418380beb43e06165b94 BUY 创建 | — | llm_chief_trader | **FLAT / 0** | — | 0.001 |
| 2c | 00:40:45.988 | Fill fill_56aa1186 成交 | **ENTRY** | — | FLAT→LONG | 0.34056 | 0.001 |
| 2d | 00:40:46.024 | Ledger txn_baa6ae35 (TRADE) | — | — | — | — | — |
| 3 | 00:40:50.441→52.457 | SELL FILLED | **EXIT** (spurious, 持仓 **6.5s**) | ai_brain | LONG / **1** | 0.34055 | 0.001 |
| 3a | 00:40:52.467 | Ledger txn_d7653017 (realized_pnl -1E-8) | — | — | — | — | — |
| 3b | 00:40:52.518 | Episode eps-7899c4b6: result=LOSS, **exit_reason=UNKNOWN** | — | — | — | — | — |
| 4 | 00:46:51.289→53.610 | BUY FILLED | **ENTRY** (cooldown 240s 自 00:40:43 起算, 00:44:43 后合法) | llm_chief_trader | FLAT / 0 | 0.34031 | 0.001 |

**无 REVERSAL 事件**: 所有 SELL 均 reduce_only=1 + position_side=LONG (只减仓,不可能反向开仓);所有 BUY 均 reduce_only=0 + position_side=FLAT (纯入场)。SPOT 市场空单不可能,隐式反转被引擎 SPOT_OVERSHORT/RiskEngine 拒绝。

### Cooldown State (事件 #2 为何能发生)
- Entry cooldown (Chief Trader, symbol-scoped 240s): 最后 ENTRY 发起于 08-29 20:40:02 → 00:40:43 时已 4h+ → **cooldown 通过** (按现有语义正确)
- 事件 #2 与事件 #1 的 EXIT 成交仅隔 **37.5s**: 不存在 exit-completion fence (旧代码),但 exit 的 order/fill/ledger/episode 终结实际已于 00:40:08.48 完成 → fence 即使存在也不会阻止 #2
- Bridge 评估 cooldown (5s): 00:40:50 评估时已满足

### Lifecycle Owner
- EXIT 归 **AI Position Bridge** (`ai_brain`, supervisor 5s 回调评估)
- ENTRY 归 **Chief Trader** (`llm_chief_trader`, 策略 tick 路径)
- 旧代码中二者无共享 per-symbol lifecycle 状态 → 所有权间隙即利用窗口

## 二、根因 (独立确立)

**Stale epoch 继承**: bridge 的 `_first_seen_open[symbol]` 在持仓平仓后经 60s+ 遗忘宽限期才清除 (grace = max(60, cooldown), `evaluate_active_positions` 末段)。事件 #1 EXIT (00:40:08) → 事件 #2 ENTRY (00:40:45) 间隔 37.5s **< 60s grace** → 新 LONG 在下一轮评估 (00:40:50) 继承已死 episode 的 first_seen = 08-29 20:40:02 → 计算年龄 14448s ≥ 14400s → **立即 spurious TIME_STOP EXIT** (事件 #3, 持仓仅 6.5s)。

**为何 00:46:53 后未复发**: 事件 #3 平仓后 TRX 缺席评估 ≥60s → `_first_seen_open` 被遗忘 → 00:46:53 新 ENTRY 触发 provider 重解析 (真实 open time) → 年龄正常 → 无 insta-exit。间歇性由此解释。

**Episode UNKNOWN 的由来** (诚实标注,非 bug): `_exit_reason_for` (trade_episodes.py) 对 strategy_id=ai_brain 的退出走 legacy 分支——需持仓时长 ≥ time_stop 才标 TIME_STOP;6.5s < 4h → 按设计落 UNKNOWN (诚实)。

## 三、修复方向验证 (与 Codex 分支实enscha一致)

Codex 修复 (branch `codex/non-strategy-infra-repair`, working tree, bridge +32/-10): **provider-authoritative epoch** — 每次评估重调 `position_opened_at_provider` (bootstrap `_position_opened_at` = MAX(entry-side fill timestamp), 权威), 与缓存差 >1s 即视为新 episode 采纳真实 open time;缓存仅作 provider 不可用时的回退。生产接线恒有 provider → TRX 路径被确定性覆盖。

**留档观察点** (供 Codex 测试设计):
1. provider 不可用回退路径仍存在理论 stale 继承 (生产不触达;可加 epoch 指纹 (entry_price, quantity) 校验兜底,或接受并记录)
2. 其余修复 (engine STALE_POSITION_STATE guard + `expected_position_version` stamp、reversal fence、fill lineage 富化、`_signal_metadata_by_client`) 在同一工作区,与指令 1-3 项对应
3. DB/运行时证据要求: 重启后应看到 TRX 新 episode 的 exit_reason 带 lineage 证据;UNKNOWN 不应被无证据改标

## 四、指令合规动作 (本方)
- staged `ENTRY_COOLDOWN_SECONDS=300` 已回滚 240 (01:20Z, .env L17) — 指令"rather than increasing cooldown"
- 校准冻结: PAPER_POLICY_STATE.md 标记 OBSERVE/HOLD gate; 无任何策略参数变更
- 并发编辑冲突: 本方 bridge constructor 编辑已完整撤出 (git diff 现仅含 Codex 修复); 遵守单写者
- 本文档为新增独立文件,不触碰 Codex 工作区文件

## 五、第二表现 (01:28Z, 同缺陷类 — exit order lifecycle 未终结)

**DOGEUSDT recon 失败** (health overall=UNHEALTHY, recon BALANCE_MISMATCH + POSITION_MISMATCH, 01:49:01):
- 21:28:37 BUY FILLED (ENTRY, 0.08511) → 持仓 LONG 0.001
- **01:28:41 SELL (ai_brain, reduce_only=1, 合法 4h TIME_STOP 时机) status=ACKNOWLEDGED — 从未终态化 (无 FILLED/REJECTED, 无 fill 行)**
- Sim exchange 侧已扣减: exchange DOGE=-0.001 / position=0;local 仍 LONG 0.001 → 本地/交易所分歧
- 与 TRX 的区别: TRX = spurious exit (stale epoch 立即平仓); DOGE = **真实 exit 卡在 ACKNOWLEDGED 未终结** → `_exit_in_flight` 抑制 (order outstanding) → 无重试 → 分歧固化直至 recon gate 亮红
- **意义**: 指令修复项 #3 (exit-completion state fence) 的直接实证 — 订单状态机存在 ACKNOWLEDGED→终态 的缺口; 修复须覆盖"submitted-but-never-finalized"路径的检测与重试
- 本方未做任何干预 (不重启/不触 DB/runtime_leases); recon fail-closed gate 按设计工作
