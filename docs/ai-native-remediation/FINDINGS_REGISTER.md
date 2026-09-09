# 两轮审计发现登记

所有项初始 OPEN_REVERIFY：来自旧审计，需在每章最新SHA复现；已修复标 VERIFIED_FIXED_WITH_EVIDENCE，不重复重写。路径相对核定工作树，不能自动视为现有缺陷。后续新增Fxx必须分配章节并经Codex同意。

| ID | 章 | 问题 | 定位线索 | 验收 | 状态 |
|---|---|---|---|---|---|
| F01 | 00 | 工作树/部署/HEAD分裂、历史报告代替事实 | Git/worktrees/HARNESS_GOAL.md | 基线、dirty保全、版本对照 | OPEN_REVERIFY |
| F02 | 00 | 旧Harness目标Binance/LIVE定位冲突 | HARNESS_GOAL.md | 当前权威指令一致 | OPEN_REVERIFY |
| F03 | 01 | 未结算入场撤单先于授权 | runtime/engine.py | 错误plan/lease不能触达adapter | OPEN_REVERIFY |
| F04 | 01 | 租约失效后循环继续、同owner恢复待安全核验 | runtime/engine.py;runtime/lease.py | 单writer/fence/release tombstone | OPEN_REVERIFY |
| F05 | 03 | 固定1盘口数量及不真实撮合深度 | runtime/engine.py;simulator/real_market_paper.py | 真实档位/量传递 | OPEN_REVERIFY |
| F06 | 03 | 慢LLM导致行情过期与采集阻塞 | runtime/engine.py | 独立采集与执行前fresh检查 | OPEN_REVERIFY |
| F07 | 03 | source timestamp用接收时间等误标健康 | market_data/okx_public_feed.py | 旧payload仍stale | OPEN_REVERIFY |
| F08 | 04 | realized_vol收益率样本恒不足 | alpha/market_data_engine.py | 金标准vol/缺失 | OPEN_REVERIFY |
| F09 | 04 | 零波动分位并列极端风险误判 | alpha/regime.py | 零序列不被误判 | OPEN_REVERIFY |
| F10 | 04 | 盘口量冒充成交量、快照与closed bars混用 | alpha/ensemble.py;alpha/features.py | 固定周期真实OHLCV | OPEN_REVERIFY |
| F11 | 04 | 多品种窗口/预热重试/40引擎长期占满 | alpha/evidence_router.py | LRU/持仓pin/重试/隔离 | OPEN_REVERIFY |
| F12 | 05 | 发现仅USDT SWAP，非全产品 | market_data/opportunity/universe.py | SPOT/linear/inverse/FUTURES覆盖 | OPEN_REVERIFY |
| F13 | 05 | 历史采集在其他dirty工作树未收敛 | market_history/ | 来源保全/覆盖/缺口/补采 | OPEN_REVERIFY |
| F14 | 05 | 配置candle_limit代替事实历史 | market_data/opportunity/service.py | 实际bar数/连续性 | OPEN_REVERIFY |
| F15 | 05 | 盘口失衡bid_qty/ask_qty未接入 | market_data/opportunity/service.py | 真实因子输入 | OPEN_REVERIFY |
| F16 | 05 | 低流动性过滤/候选排序可能限制全市场观察 | market_data/opportunity/eligibility.py | 四层分离无因子硬门控 | OPEN_REVERIFY |
| F17 | 02 | 产品ID模糊和强制LINEAR_PERP | exchange/symbol_mapper.py;llm_chief/runtime_strategy.py | 产品不混、迁移不猜 | OPEN_REVERIFY |
| F18 | 06 | Risk未传真实日盈亏与回撤 | runtime/engine.py;risk/engine.py | 实际限额触发 | OPEN_REVERIFY |
| F19 | 06 | 多币余额/权益/反向合约/敞口公式不统一 | ledger/;portfolio/;exposure/;risk/ | 跨消费者notional/PnL一致 | OPEN_REVERIFY |
| F20 | 06 | funding=0和成交-账本分步恢复风险 | governance/trade_episode.py;runtime/engine.py | 费用资金费/幂等恢复 | OPEN_REVERIFY |
| F21 | 07 | Sizing/杠杆缩量及手数全路径仍需证明 | sizing/;risk/;llm_chief/runtime_strategy.py | 同plan/方向批准参数到order | OPEN_REVERIFY |
| F22 | 08 | 因子/研究/记忆名字存在但接线浅 | llm_chief/context_loader.py;llm/tools/ | 真实调用和as-of | OPEN_REVERIFY |
| F23 | 08 | 规则confidence与数据可靠度/胜率混淆 | alpha/ensemble.py;alpha/sub_strategy/ | 概率未校准为null | OPEN_REVERIFY |
| F24 | 08 | trend/momentum/breakout共源证据重复 | alpha/sub_strategy/ | 独立性/反证/适用条件 | OPEN_REVERIFY |
| F25 | 08 | FundingBasis组合未注册、单位/持有期不足 | alpha/sub_strategy/funding_basis.py;llm/tools/alpha.py | 工具清单/成本口径 | OPEN_REVERIFY |
| F26 | 08 | 工具超时预算、身份/未来时间、记忆TTL不足 | llm/tools/registry.py | 失败不造证据/选择权保留 | OPEN_REVERIFY |
| F27 | 09 | 异常attempt和不可变Evidence未完整durable | llm_chief/decision_store.py;llm_chief/position_manager.py | 请求中断/版本/引用重放 | OPEN_REVERIFY |
| F28 | 10 | 真实启动全生命周期及legacy隔离需验收 | runtime/bootstrap.py;llm_chief/position_manager.py | 多空partial/restart/duplicate/fullclose | OPEN_REVERIFY |
| F29 | 11 | 回测反手盈亏符号错误 | governance/backtest.py | 手算多空翻转 | OPEN_REVERIFY |
| F30 | 11 | 费用未入净权益、收益序列/指标不正确 | governance/backtest.py | 净值/逐期收益/不可用指标 | OPEN_REVERIFY |
| F31 | 11 | 固定BTC/时间/volume等不等于事实回放 | governance/backtest.py | 真实输入与fixture分开 | OPEN_REVERIFY |
| F32 | 12 | walk-forward评分器不是真样本外执行 | validation/walk_forward/engine.py | 窗口/防泄漏/消融/失败样本 | OPEN_REVERIFY |
| F33 | 13 | local midnight取当天、失败补跑/1000条截断 | governance/scheduler.py;governance/trade_episode.py | UTC前日/SQL分页/补跑 | OPEN_REVERIFY |
| F34 | 13 | 学习主要WIN/LOSS标签、复盘重复增版本 | governance/factual_learning.py | 因果证据/唯一revision/安全回流 | OPEN_REVERIFY |
| F35 | 14 | 前端展示不等于事实健康与链路完整 | api/;frontend/ | API按钮/状态/DB对账 | OPEN_REVERIFY |
| F36 | 15 | 迁移仅连接检查/自然及持续健康未全部实证 | runtime/bootstrap.py;tests/ | schema revision/24h/自然链路 | OPEN_REVERIFY |
| F37 | 00 | Harness失活误判/无限重启/未认证审批风险 | 监督运行协议 | 精确身份/锁/限额/回执来源 | OPEN_REVERIFY |
