# 共模候选一次空载状态机实验 — 2026-10-19

## 结论

本轮一次原START，状态机自行运行到**NO_ROTATION**，未按2秒提前截断，未强推CONTACT/TIGHTEN，未升流或修改保护。
约5.3秒UART观察到terminal；运动断续、无法建立持续运动条件，**没有通过20rpm跟踪或完整拧紧验收**。

没有底层ADC/过流/encoder/时序保护故障；NO_ROTATION属于流程失败，不应和底层CURRENT_INVALID或硬过流混淆。
`CONTACT=0`、`RUNDOWN_ARMED=0`、没有OK，说明未因低速高Iq误走接触成功路径。
此处NO_ROTATION意为“持续起转未建立”，不是编码器完全没有位移。

## 身份与动作边界

- 精确镜像：`TighteningCommonModeCandidate` A，229308B。
- BIN SHA256：`814d6254a29dfe186309f35b00a8dc1752a597f6bc8b51f2254f19dff03fa886`。
- ELF SHA256：`84740c33e5dbd222251a7b15a4b7c8dff1989941d056b4cda9094fa3d1a8e391`。
- 上板前人工确认12V关闭、MCU供电、电机空载固定、IU→PA0/IV→PA1/PC6→CTRL_SD不变，仅允许非活动A。
- stage：`tmp/cm-fsm-stage-1792419119948479100.json`；完整及独立回读通过，B729应用/bootloader/私有配置与meta未变。
- run：`tmp/cm-fsm-run-1792419626908641700.json`；完整Flash/RAM、快照及哈希在收据，保持本地不公开。
- 人工开启12V、限流0.5A、无报警且现场可立即断电；正常bootloader trial/5s健康确认并复位，确认A732；未强制confirm。
- 精确profile实测包含`CM=85`、SB3、1.6V vector limit、原12s lease。
- 原RAM RUNDOWN_RPM=70，临时设20并回读；结束后恢复70、没有SAVE。原各段电流时间及全部限幅/保护未改。
- 只发一次START（请求7832），主机守候上限11.95s，原板端12s lease保留。流程在此之前自行失败停机，无自动重试。

## 前置与结束证据

| 项目 | 值 |
|---|---:|
| 零点 valid/reject/total | 4000 / 41 / 4045 |
| max consecutive reject | 1 |
| zero U/V | 1560 / 1563 |
| MotorControlTask stack free预检 | 2644B，6次观测 |
| 预检FOC wall max | 29.858µs |
| 全轮FOC wall max | 31.535µs |
| deadline miss | 0 |
| actual CCR commit | 241960 |
| actual CCR late | 0 |
| actual min margin | 15.176µs |
| CUR_CONFIRM enter/clear/fault | 93 / 93 / 0 |
| CUR_CONFIRM max cycles/elapsed | 2 / 101µs |
| 底层MOTOR TEST FAULT VALID/FLAGS | 0 / 0 |

普通`ADC TIMING LATE`为原hypothetical/coarse尾部计数，不等于真实CCR late；本报告明确使用独立actual账本，不清计数。
零点total保留板端原统计，不能擅自改写为valid+reject。
预检stack为MotorControlTask，不是ProtocolTask/全调用链high-water证明。

## 运动与流程

```text
IDLE → PRECHECK → RUNDOWN_START → NO_ROTATION
                                    → OFF / FAILED
```

需求Iq逐步上升，但速度多次短促升高后回落甚至反向；高需求持续后，运动建立条件始终未满足，按原门控判启动失败。
不能把单次速度峰值超过10rpm或累计几十度位移，等同于连续100ms双速度达标且同窗正向位移≥3°。

UART终态：5.298s，OUTCOME=NO_ROTATION、CONTACT=0、MODE=IDLE、BUSY=0、FLT=0；FSM扩展日志为NO_ROTATION/OUTCOME=FAILED/FAULT_REASON=NO_ROTATION。
流程首快照：domain=PROCESS(3)、legacy outcome reason=7，底层protection_flags=0；该快照在输出关闭后保存，IqRef已清0，不能把它与停机前Iq作同步跟踪对比。
快照编码器位置约44.98°，随后UART位置约40.4～40.7°，显示停机/回摆阶段也有变化；不是连续均速转动或机械转矩测量。
末段运行STATUS IqRef到385mA，仍是原速度PI动态给定、限幅0.40A，不是固定0.45A实验。

## 共模路径本轮覆盖范围

SRAM解码：plans=243388，adjusted=0，rejected=0，last_offset=0，max_abs_offset=0，min_slack=203ticks。

本轮启用了新planner且所有实际计划通过，**但没有任何command需要真正同量平移**。
因此只能说明本输入范围下兼容/时序通过、未出现窗口拒绝；不能据此宣布已在实机上验证“-87ticks平移”或证明旧ADC窗口故障因共模分配而消失。
保留的A728故障command在离线可生成合法平移结果，与本轮实物覆盖范围是两件事。
本轮亦再次说明：采样窗口/CCR时序通过，不等于断续运动和低速扭矩链已解决。

## 收尾与待做

STOP/ANALOG SAFE已回读SD=0、MOE=0、FOC=0；调试器再次关输出并halt。
A/B应用、bootloader、私有字节未变，仅正常trial/confirm更新启动metadata到A732。
人工确认12V关闭后，已仅恢复原B启动选择，元数据B733，pending=0、attempts=0；停在B应用入口，没有运行B应用或再次启动电机。
恢复收据：`tmp/cm-fsm-restore-1792419772420780500.json`。完整Flash回读确认A/B应用、bootloader和私有区未变，仅正常启动元数据更新；SD=0、BDTR=0、CCER=0、MCU halt。
板测脚本`tools/common_mode_fsm_board.py`的5项定向门禁/one-shot/错误收尾回归通过；未改本轮已编译固件。
