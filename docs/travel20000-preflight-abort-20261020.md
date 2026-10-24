# 20000° 候选：启动健康窗 CURRENT_INVALID，未启动电机

结果：本次没有发送 START（start_attempts=0），没有运行 240 rpm 状态机或电机。初始零点校准通过，但正常 5 秒启动健康检查即将完成时触发 CURRENT_INVALID，脚本按保护中止，没有自动重试、强制确认或修改阈值。不能据此评判 20000° 的实际运行效果。

## 配置与启动

用户本轮确认已开启 12 V、无报警，沿用 12 V / 限流 0.5 A、电机空载固定及原接线，人在现场可断电。

- 新 A preset：Tightening240rpmTravel20000Candidate。
- BIN SHA256：`585410c17c75142dc07db3a6b6567500a212b167435f108a59b3b4364f2c2325`。
- 启动日志明确显示 `RAM=240rpm TRIP=300rpm SAVE=OFF` 和 `TRAVEL=20000deg RAM only`。
- 零点：valid=4000、reject=54、total=4055、reject_rate_ppt=13、max consecutive=1、zero U/V=1559/1563、result=1、ZERO=3。
- total 保留原滑窗实现的统计口径，不改写为 valid+reject。
- 正常 A/B 试运行已提交，B 仍 confirmed、A pending，attempts=1，generation=743；A 没有健康确认。
- UART 最后健康观测为 HSTABLE=4000ms，随后 MOTOR TEST STATE=FAULT。故障快照 state_elapsed_ms=4850，仍在 5 秒健康窗内，MODE=IDLE、speed command=0、IqRef=0，SD/MOE/CCER 均关闭。

## 停机证据

首次故障快照：

- domain=PROTECTION（2），fault reason=11（CURRENT_INVALID）。
- current validator state=SUSPECT（1）。
- unresolved consecutive=3、max consecutive=3；未改原 limit=3。
- unresolved total=24、suspect total=809、confirmed spike=759、confirmed transition=38。
- encoder valid=1、errors=0。
- 机械位置约 −0.044°、CTRL≈−0.209 rpm，仅是静止附近编码器变化，不能记作启动运动。
- 快照 Iq≈0.334 A、Id≈0.037 A，但功率输出关闭；这只是采样/变换反馈值，不证明有实际 0.334 A 相电流，也不能仅凭这一帧区分模拟毛刺、偏置、映射或状态机具体原因。

本次正式构建没有启用故障前后原码 trace，未取得逐帧原码窗口，因此不能断言是三次连续物理毛刺，或把原因归于 20000° 参数。可确定的是启动反馈判别无法连续解释三个决策周期，原 CURRENT_INVALID 保护工作并阻止 START。

时序仅覆盖功率关闭的启动计算：

- FOC wall max=29.894118 µs；deadline miss=0。
- actual CCR commit=100997，late=0，min margin=16.641176 µs。
- CUR_CONFIRM=54 enter / 54 clear / 0 fault；max cycles=2、max elapsed=100 µs。

这不是 CUR_CONFIRM 故障，不是 8 秒运行超时，也不是行程到限。没有闭环运行阶段，不能将启动时序数据说成带电运动验收。

## 输出关闭与 B 恢复

检测故障后发送 STOP/ANALOG SAFE 并 SWD halt，完整保存同镜像 Flash/RAM；未重新试运行 A。

用户随后确认 12 V 已关闭。恢复脚本原先只接受“已确认 A”状态，本次增加仅接受这次已知 `(confirmed B, pending A, attempts 1)` 的恢复门控；完整回读、镜像 CRC、B/boot/private 及收据哈希门控不变。对这两种已知状态都仅发送原 bootloader `SET_CONFIRMED_SLOT B` 命令，清除 pending；不发送 `CONFIRM_CURRENT A`，在 B 应用 Reset_Handler 入口硬件断点停住。

新增模拟测试验证 pending-A 恢复只选择 B、包含 B 入口断点、拒绝其他尝试状态；该脚本 7 项测试通过。未修改 bootloader、IAP、控制固件或保护阈值。

- 运行收据：`tmp/travel20000-fsm-run-1792459632131080000.json`。
- 运行全 Flash SHA256：`85019376b7e690a329c100001dc91c43b9fcfe9aa506b9d2b0118b7385f2bed9`。
- 恢复收据：`tmp/travel20000-fsm-restore-1792459768815367800.json`。
- 恢复全 Flash SHA256：`e0d3945a1515c0fc10a9ea435ae2549ecd115b4a985b7303e2dc116854ee43cb`。
- 最终 confirmed B、pending none、attempts=0、generation=744。
- SD=0、MOE=0、CCER=0、MCU halted、B 应用未运行。
- A/B 应用、bootloader、私有配置完整对比未变，仅由原 bootloader 更新启动元数据；原始 Flash/RAM 留在本地忽略目录，不公开私有字节。

本轮已停住，未再次启动。若后续重新试验，须根据恢复后的 B744 精确状态建立新的核验基线，不能直接绕过旧 stage 收据/基线检查。
