# 原运行配置 DQ ON 单次空载复测

运行回执 `tmp/dq-fsm-run-1792583552935164100.json`。
使用 `DqOriginalRuntime`：BIN与旧已跑240 rpm的WireCandidate逐字节一致，
不含新增DQA每帧统计/反号实验；DQ ON读回通过。
只发送一次START，未改PI/限幅/编码器期限/控制算法，未自动重试。

校准 PASS，4000 valid / 53 reject，U/V零点1560/1563。
启动健康检查/时序预检PASS，正常由bootloader确认A，元数据generation923。

实测：

| 指标 | 本次 |
|---|---:|
| 运行阶段 | 原RUNDOWN，8秒后自然RUNDOWN_TIMEOUT |
| CONTACT | 0，无强制接触/OK |
| STATUS运行观察数 | 144 |
| 末段约0.35秒平均控制速度 | 238.933 rpm，6点 |
| STATUS观测峰值 | 244.2 rpm，非全速率峰值 |
| 既有1kHz聚合超调 | 6.458 rpm |
| 稳定运动延迟指标 | 325 ms，非首次机械动作时刻 |
| 加速段MAE | 10.797 rpm |
| 匀速段MAE | 3.867 rpm |
| IqRef绝对峰值 | 401 mA |
| 测得Iq绝对峰值 | 1192 mA，既有observer峰值，不是平均值 |
| 速度积分器绝对峰值 | 112 mA |
| 速度Iq饱和累计 | 0 ms，不等同dq电压饱和 |
| FOC wall max | 33.3471 us |
| 50 us deadline miss | 0 |
| 实际CCR late | 0 |
| 实际CCR最小margin | 15.1471 us |
| CUR_CONFIRM enter/clear/fault | 142/142/0 |
| 独立编码器/过流等保护 | MOTOR TEST FAULT VALID=0 FLAGS=0，最终FLT=0 |

末态first_fault的domain3/reason3/protection_flags0来自原状态机RUNDOWN_TIMEOUT，
不是编码器事务超时、CURRENT_INVALID或FOC deadline故障。脚本保留原
`pass_=false`/退出码1及自然超时结果，不能把空载运行完成改成拧紧成功。

本次未出现上次201us编码器事务故障，但一轮成功不足以证明它已永久消失，
或证明诊断插桩是唯一原因。旧200us期限仍在本镜像中。
新增DQA已关闭，所以本次不能补齐旧任务要求的前500ms同帧电压诊断。
Tokenized日志仍收集；没有新发交替DQ UART查询，旧字段中的“sparse queries”
是继承描述，不表示这次确实发了这些额外查询。

最终SD/MOE/AOE/CCER关闭，MCU halted；完整Flash/SRAM已保存，
boot/B/private字节在运行前后核对未变。

人工随后确认12V关闭，已仅通过原bootloader流程恢复B启动选择并停在B入口：
`tmp/dq-fsm-restore-1792583654913763900.json`，PASS。
SD=0、BDTR=0、CCER=0、DHCSR=0x30003、VTOR=0x08040000；
B应用未运行，motor_commands=0，A/B应用与私有配置除启动元数据外未变。
后续暂存应以本回执的最新完整Flash作为基线，不复用旧B920捕获。
