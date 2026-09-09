# 验收矩阵

初始全部NOT_VERIFIED；文档契约测试不改变章节状态。每行完成后填candidate SHA、test日志摘要、Codex来源及时间，禁止只填PASS。

| 验收ID | 章 | 发现ID | 必须通过 | 状态 |
|---|---|---|---|---|
| A00 | 00 | F01,F02,F37 | 完整提交/驳回/修复重提/批准，过期 SHA 和重复请求不能放行。；明确故障恢复、两次卡住确认、长测试/待审/暂停不恢复、认证/额度失败不重启、Retry-After、上下文压缩和限额。；中断恢复不重复提交推送；锁竞争仅一个恢复者；旧进程未退出不启动新写入者；Codex失联不自批。 | NOT_VERIFIED |
| A01 | 01 | F03,F04 | 错误token/owner/fence、过期/显式release后恢复、renew异常/false。；合法未结算开仓取消、伪造持仓动作、重复取消、并发抢租约。；故障后执行拒绝；首TTL后持续续租、重启唯一writer。 | NOT_VERIFIED |
| A02 | 02 | F17 | BTC现货/永续/到期/反向ID互不混淆；非BTC实例。；精度、规格缺失、退市/到期、抵押币缺失。；迁移升级/回滚或向前修复演练；历史证据不变。 | NOT_VERIFIED |
| A03 | 03 | F05,F06,F07 | 慢模型/超时不阻塞行情与续租；过期报价安全拒绝。；乱序/重复/丢序、盘口单位和部分成交、缺深度。；来源时间旧但接收新仍STALE；同symbol不同产品不串用。 | NOT_VERIFIED |
| A04 | 04 | F08,F09,F10,F11 | 已知收益率/波动手算、常数序列、样本不足。；同一时间不重复ingest；未来/乱序bar拒绝或隔离；重启一致。；超过40品种轮换、持仓保留、失败预热可恢复。 | NOT_VERIFIED |
| A05 | 05 | F12,F13,F14,F15,F16 | 活跃集合+轮换公平性，非USDT产品发现，无因子触发仍可观察。；批量限制、请求配额、缺历史/不连续、下架、重试与断点恢复。；原始来源与API覆盖对账，不创建无限WS。 | NOT_VERIFIED |
| A06 | 06 | F18,F19,F20 | 各产品同一案例跨Risk/Portfolio/API/reporting对比无差异。；日亏损、回撤、旧价格/缺价格、资产单位触发测试。；中途数据库异常、重复fill、重启replay、journal平衡。 | NOT_VERIFIED |
| A07 | 07 | F21 | long/short批准/缩量/拒绝；大小账户、高低波动、min lot、非1contract size。；无效/缺失/非有限杠杆、超过上限、流动性限制。；批准qty/leverage真正到达OrderIntent，ID和方向保持。 | NOT_VERIFIED |
| A08 | 08 | F22,F23,F24,F25,F26 | 不同上下文Chief可选不同工具；无触发不禁交易；工具不创建plan/order/risk审批。；过期/异币/未来证据、工具timeout、重复证据、未经校准概率。；研究/记忆as-of和source可追溯，工具部分失败保留其他事实。 | NOT_VERIFIED |
| A09 | 09 | F27 | NO_TRADE/WAIT/异常/取消后节流；跨重启去重。；schema恶意/畸形/非有限/额外字段；模型自带ID不可信。；崩溃于request/persist间可恢复；证据hash/引用不变。 | NOT_VERIFIED |
| A10 | 10 | F28 | 真实build_system+受控Provider边界长短两套自动链路。；部分entry、REDUCE、部分EXIT、重复退出、重启、并发fill。；HOLD零单/ACTIVE；提交单不关闭；legacy不能执行；无反转。 | NOT_VERIFIED |
| A11 | 11 | F29,F30,F31 | 手算多/空上涨下跌、反手、双边成本、部分平仓。；账户权益逐步核对、无交易/无亏损/不足样本、不规则时间。；linear/inverse/spot、费用funding、最后一笔平仓规则。 | NOT_VERIFIED |
| A12 | 12 | F32 | 时间边界、防未来数据/存活偏差、测试集不可回灌。；完整失败报告、成本敏感性、样本不足标未验证。；walk-forward确实执行窗口，不只是输入performance生成score。 | NOT_VERIFIED |
| A13 | 13 | F33,F34 | 跨UTC日、漏日、1000+条、重试、重复复盘。；无fill不产episode，部分reduce不关闭，重复close一个episode。；复盘Provider失败不影响会计事实，记忆as-of/反例及引用可重放。 | NOT_VERIFIED |
| A14 | 14 | F35 | frontend npm test/typecheck/build；真实浏览器操作与只读DB/API对账。；404/500/timeout、离线恢复、无数据、版本不同、无权限。；表单提交不重复、按钮不触发LIVE/秘密读取。 | NOT_VERIFIED |
| A15 | 15 | F36 | 无无计划entry订单/fill、无重复plan/decision/episode、无反向reduce、账本一致。；自然模型请求非health probe，真实ID和UTC时间链路完整。；中断恢复按安全授权；连续健康窗口故障后解释并重验受影响窗口。 | NOT_VERIFIED |

## 监督负测 W01–W12（第00章）
| ID | 行为 | 预期 |
|---|---|---|
| W01 | 明确模型错误 | 诊断后有界恢复，不改模型 |
| W02 | 长测试/迁移/Git有效写入 | 不重启 |
| W03 | 疑似卡住 | 两次独立间隔巡检和deadline佐证 |
| W04 | 暂停/待审/权限等待 | 保持，不能跳章 |
| W05 | 无额度/认证/无模型权限 | 告警，不重启 |
| W06 | Retry-After | 延后到允许时间，跨恢复保留 |
| W07 | 上下文超限 | 精简检查点，不原样重发 |
| W08 | 重复事件/并发监督 | 单恢复锁，一次attempt |
| W09 | 1h/24h限额及重启 | 滚动2/6次不清零 |
| W10 | 旧writer/子进程未退出或PID复用 | 不启动第二writer |
| W11 | 检查点恢复 | dirty/提交/审核保留，不重复副作用 |
| W12 | 交易/Codex离线 | 交易不动；监督缺口不报告健康 |

## 全局最终条件
ENGINEERING / HARNESS_SUPERVISION / RUNTIME / NATURAL_LIFECYCLE / CODEX_FINAL_APPROVAL分别记录。
全backend pytest、Ruff、frontend test/typecheck/build、migration/recovery、24h跨UTC午夜健康与TTL续租、真实DeepSeek+OKX。
entry decision→plan→Risk→order→fill→position ACTIVE；OPEN review→reduce/exit→fill→qty0→CLOSED→episode→review→memory。
无无计划entry、无重复decision-plan、无反向reduce、无重复episode、notional mismatch=0、journal平衡。
无自然entry/exit为PENDING_NATURAL_EVIDENCE，不是COMPLETE也不是调参许可。
