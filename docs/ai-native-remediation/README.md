# AI 原生系统修复任务包
版本：1.0；生成日期：2026-09-09。最新核验候选工作树：crypto-auto-trading-system-fullmarket，分支 codex/full-market-factor-layer，快照 fc244d470cad1536085834c4f77ae47b2688cb6a。进入任务时必须重核，不把快照当永久最新。

## 给 Harness 的入口
可直接使用 [指定会话启动指令](HARNESS_START_HERE.md)。交付范围与未验证项见 [交付记录](DELIVERY_REPORT.md)。
首先完整阅读 [MASTER_HARNESS_INSTRUCTIONS.md](MASTER_HARNESS_INSTRUCTIONS.md)，只执行获授权的当前章节，从 [第00章](chapters/00-supervision-review-and-baseline.md) 开始。不要一口气跨章实现。

## 给 Codex 的入口
阅读 [审核指令](CODEX_REVIEW_INSTRUCTIONS.md)、[巡检恢复规则](HARNESS_WATCHDOG_AND_RECOVERY.md) 和 [本机接入实况](LOCAL_INTEGRATION_STATUS.md)。每章审核与恢复是独立权限，不能互相替代。

## 状态与事实
本文档包完成不表示任何交易章通过。第00章本机通信/恢复演练必须另行提交证据，当前不允许凭文档或JSON自行启用自动恢复。
全系统完成需工程、监督、运行、自然生命周期全部PASS。无自然交易允许等待，不伪造。运行状态以真实来源为准。

## 导航
- [权限与安全](AUTHORITY_AND_SAFETY.md)
- [发现登记](FINDINGS_REGISTER.md)
- [验收矩阵](ACCEPTANCE_MATRIX.md)
- [变更控制](CHANGE_CONTROL.md)
- [机器清单](manifest.json)
- [提交模板](templates/CHAPTER_SUBMISSION.md)
- [审核模板](templates/CODEX_REVIEW.md)
- [运行授权](templates/RUNTIME_AUTHORIZATION.md)

## 校验（不会启动交易/恢复代理）
从仓库根执行 python3 scripts/test_remediation_package.py。
完整JSON Schema语义校验使用 scripts/check_remediation_schemas.py；需独立可用的jsonschema>=4，不能将缺依赖写成通过。校验只验证格式，不证明审批身份或运行安全。

复现依赖清单：scripts/remediation-validation-requirements.txt。在独立校验环境安装，不修改交易虚拟环境。再执行 python scripts/test_remediation_schemas.py。持久审批来源、进程锁、次数上限等行为必须由第00章实现并实测；此格式测试不能证明这些行为已经存在。

## 运行材料
本项目 .ops/ai-native-remediation/ 专用于脱敏请求、检查点、监督事件，不入Git；测试会话单独放 .ops/ai-native-remediation/drills/。不要把.env、原始Provider响应、密钥或生产DB复制进提交。
