# Harness 巡检与恢复运行手册
## 当前开关
恢复默认 DISABLED_UNTIL_CH00_APPROVED。本机identity与resume/stop/start入口未验证，不执行重启。文档存在不等于功能已上线。
使用同一Codex heartbeat做审核+健康巡检；不重复建立系统cron或第二监督者。

## 频率和限额
每10分钟巡检；明确可恢复故障经诊断进入恢复，疑似卡住要两次不同巡检（至少10分钟间隔）确认。每滚动1小时最多2次、24小时最多6次，失败也计入；从开始恢复起先落盘计数，进程重启不清零。
默认恢复后观察最多两次巡检（20分钟）：真实工作进展才算成功；仅进程存在不算。未证实成功记RECOVERY_FAILED，不继续高速重试。
单次恢复lock包含owner、attempt_id、会话、启动时间；使用OS持锁/原子机制，不仅检查文件存在。持久化计数、状态、通知去重；锁不明时不强抢。

## 判断矩阵
RUNNING且有效长测试/迁移/Git写操作→等待，不按无日志/无commit重启。
WAITING_FOR_REVIEW→审核；PAUSED_BY_USER→保持；WAITING_FOR_USER→通知不绕过。
模型timeout/transport/session terminated→核对明确错误与活动工具，再恢复。
疑似stall→连续两次检查、模型/操作deadline已过、无有效活动工具，才可恢复。
429/Retry-After→BACKING_OFF至允许时刻（跨重启保留）；401/403/无额度/模型无权限→WAITING_FOR_USER。
context overflow→先生成精简checkpoint，不把原超限上下文重发；不切模型/不消费reset。
Provider不可达→有界退避且计入恢复预算，不无限重启。
PENDING_NATURAL_EVIDENCE、NO_TRADE/WAIT或模型拒绝不安全请求不是故障。

## 恢复事务
1. 获取精确项目监督锁；核验session、process PID+start time、project、操作子进程归属、已批准chapter。
2. 记录安全checkpoint和恢复attempt；dirty内容仅hash/路径/状态，保留文件本身，不复制秘密。
3. 优先现有会话resume；不能resume才按核验过的停止接口请求停止。不能确认副作用是否已完成，先只读对账。
4. 原进程及所属写入子进程安全退出之前不启动新工程writer；PID复用需重新核验。不得中断有效迁移/Git写操作。
5. 使用已验证允许列表入口和原模型/预算配置启动唯一实例；不接受队列中任意shell命令。
6. 读取相同checkpoint、实际HEAD/status/log、最新真实Codex回执，续作当前章。待审继续待审，已完成操作不重复。
7. 用新模型响应+一次合法工具/任务进展确认恢复；检查交易服务PID/lease未被操作。
8. 写结果并释放锁。失败、达到上限、成功均通知一次；普通健康和未变化静默。

## 必须逐项演练
见第00章：明确错误、两次卡住、长测试、暂停、待审、认证/无额度、Retry-After、上下文溢出、并发锁、PID复用、滚动限额、checkpoint恢复、未知子进程、安全停止失败、Codex离线。
演练是专用非交易会话；不得宣称为生产自然证据。

## 可用性限制
电脑开启且Codex app可用才可依赖本地计划任务；记录last_supervision_at（UTC）。监督自己离线无法当时通知，下一次恢复检测到gap须补报，不能把空档写成健康。
来源：[OpenAI官方计划任务](https://learn.chatgpt.com/docs/automations)。宿主能力/目录权限要本机实测，不绕过平台sandbox。
