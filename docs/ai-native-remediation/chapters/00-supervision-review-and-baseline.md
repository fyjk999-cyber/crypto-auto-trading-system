# 第 00 章：监督、自动审核与版本基线

状态：READY_FOR_IMPLEMENTATION（不是已实现或已批准）。先阅读 [总指令](../MASTER_HARNESS_INSTRUCTIONS.md) 和 [安全边界](../AUTHORITY_AND_SAFETY.md)。

## 目标与前置批准

先证明代理协作可靠，再开始交易修复。当前候选 fullmarket HEAD fc244d470cad1536085834c4f77ae47b2688cb6a；这是核验快照，不是永久最新版本。

本章为启动关卡；必须由实际 Codex 审核输出批准，不能自举伪造审批。

## 允许修改与禁止范围

HARNESS_GOAL.md、监督接口、文档、隔离演练；不改交易逻辑、不启停交易运行时。

发现依赖或跨章修改，提交变更请求；禁止悄悄扩大范围。若缺陷已被新提交修复，保留回归证明而非重复实现。

## 实施任务

1. 核对 origin、分支、worktree、HEAD、运行 SHA、DB、未提交文件及内容摘要；保留用户工作，旧分支有效改动逐项比较。
2. 修订旧 HARNESS_GOAL 中 Binance 优先、策略非核心、LIVE 可运行等冲突；保留其账本、幂等、安全设计，旧文档标为历史而非直接删除。
3. 建立当前 Codex 任务的单个10分钟 heartbeat；验证会话身份、状态读取、检查点、确切续作入口；禁止直接采用按端口杀进程脚本。
4. 实现审核请求→Codex 独立回执→Harness 验证回执流程；同用户共享 JSON 不是批准来源。队列 schema 与来源核验是两道独立关卡。
5. 隔离演练可用明确标注的测试会话/固定测试数据，不可写入交易 DB、伪装自然交易；锁、恢复计数必须持久化。

## 测试与回归

- 完整提交/驳回/修复重提/批准，过期 SHA 和重复请求不能放行。
- 明确故障恢复、两次卡住确认、长测试/待审/暂停不恢复、认证/额度失败不重启、Retry-After、上下文压缩和限额。
- 中断恢复不重复提交推送；锁竞争仅一个恢复者；旧进程未退出不启动新写入者；Codex失联不自批。

先最小回归再正式装配集成；所有后台/工具测试使用隔离DB和fixtures，不读取真实凭据、不写生产PAPER数据。涉及后端执行相关pytest及ruff check .；涉及前端执行npm test、npm run typecheck、npm run build。完整命令/退出码/日志不能截断。

## 交接证据

- 基线清单、脏文件保全摘要、身份绑定和已验证入口证据。
- 真实通道往返和受控演练回执，逐项区分模拟测试与本机实证。
- 填写 [提交模板](../templates/CHAPTER_SUBMISSION.md)，对应本章发现ID和验收ID。
- 固定base/candidate完整SHA；记录pre-existing dirty摘要、actual changed files、测试环境及日志hash；未验证不能写PASS。

## Codex 审核与放行

通道或入口未验证必须 CHANGES_REQUIRED/待证；不得将文档或测试通过当作操作授权。

Codex复查真实diff和关键用例，填 [审核模板](../templates/CODEX_REVIEW.md)。Harness不得将自己生成的result当批准。任何候选SHA变化，相关批准需重核。通过才进入下一章；不通过按问题ID返工。

## 回滚与失败处理

代码以独立章节提交保留回退边界；未经授权不得git reset/clean或重写用户历史。迁移先用副本验证可逆/向前修复方案，不盲目downgrade生产库。运行异常按已批准启停方案受控停止；不得手改lease/订单/资金。恢复Harness只续作本章，不重启交易系统。
