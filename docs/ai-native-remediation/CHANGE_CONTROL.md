# 变更、证据和运行授权控制
## 不覆盖旧工作
开始时保存HEAD、branch、remote和dirty路径/hash。报告不保存秘密内容。旧canonical/fullmarket/p0p1/infra改动逐项compare，不整库覆盖，不reset/clean。未知并行提交出现时暂停涉及文件写入，重核基线。

## 章与分支
按manifest顺序一次一章；待审只读预研。独立codex/remediation-XX-topic分支，原分支不force-push。提交只stage本章文件（不要git add .）；运行日志不入Git。schema/契约变更须旧新兼容和迁移证据。
跨章依赖/更改风险阈值/策略参数先发变更请求：before、reason、evidence、scope、test、rollback；Codex明确授权后方可做。

## 审核状态
READY→IMPLEMENTING→SUBMITTED→IN_REVIEW→APPROVED；CHANGES_REQUIRED返工产生新request。只有真实Codex来源批准SHA才有效。队列result格式正确不等于身份可信。
实际快照内容变化，批准失效范围至少包含受影响文件与依赖；最后集成版本再跑完整回归。没有“超时自动批准”。

## 证据保留
日志UTC、环境版本、命令与exit_code完整，hash绑定；截断=NOT_VERIFIED。限制日志引用到项目运行证据目录并防路径穿越。checks.json只放总结/引用，不放raw model/auth/env。使用本机snapshot或DB只读模式，测试绝不写canonical DB。
不可得provider样本/无自然交易明确待证。不能将样本外研究或模拟fixture当作自然验收。

## PAPER部署
普通chapter approval不授权启动。运行授权需SHA、DB、pending orders/positions、PID/lease现状、预算、有限操作范围、回滚/停止触发、到期时间。Codex批准安全方案后Harness执行；不得人工清lease、不造账户余额或成交。Harness恢复权与交易启动权严格分开。
