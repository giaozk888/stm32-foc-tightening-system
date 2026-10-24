# Intent FSM 首轮空载板测 — 2026-10-19

## 结论

已完成一次人工授权的候选 A 上板及空载 START；**空载闭环验收未通过**。
预检、原 A/B 自动健康确认及零点通过；运动仍断续，约 1.7 s 后底层保护停机。
未重试、未自动升流、未修改 PI/保护阈值；没有 CONTACT 或 OK。

运行结束先停在 A728。人工确认12V关闭后，已通过原bootloader mailbox恢复原B启动选择，元数据B729；停在B应用入口，SD/MOE/CCER关闭、MCU halt，未运行B应用。

## 镜像及证据

- A: `TighteningIntentCandidate`，229220 B。
- BIN SHA256: `f010e5a63ce2e0cc7362b91809ac4bb5c2c53708c4be22ab6efe472e2169cda9`。
- ELF SHA256: `6594f451d10943761b2542dbd207e6ea0abeb00cf218a3c56a840f19e72b2b10`。
- stage receipt: `tmp/intent-fsm-stage-1792411265577937300.json`。
- run receipt: `tmp/intent-fsm-run-1792411352445848100.json`。
- Flash/RAM 路径及哈希存于 run receipt；完整备份仅本地保存，不公开私有配置。
- 暂存及独立回读通过；B725 原应用、bootloader、私有配置未变；运行期间仅正常 A/B 元数据更新到 A728。

## 测试边界

12 V、供电限流 0.5 A；U/V/W 接回，电机空载固定，IU→PA0、IV→PA1、PC6→CTRL_SD。
一次原 UART START（请求7830），目标 20 rpm，主机计划约2s后STOP；原板端12s lease未改。
原 RAM recipe RUNDOWN_RPM=70，临时改20并回读，停止后恢复70；未 SAVE。
speed PI Iq cap仍0.40 A；并未使用之前固定0.45 A/150rpm诊断镜像。

## 实测

| 项目 | 结果 |
|---|---:|
| 零点 accepted valid | 4000 |
| reject / total / max consecutive reject | 54 / 4055 / 2 |
| zero U / V | 1561 / 1564 |
| 预检 FOC wall max | 28.211 µs |
| 结束快照 FOC wall max | 33.441 µs |
| deadline miss | 0 |
| actual CCR commit | 168157 |
| actual CCR late | 0 |
| actual minimum margin | 15.194 µs |
| CUR_CONFIRM enter / clear / fault | 68 / 68 / 0 |
| CUR_CONFIRM max cycles / elapsed | 2 / 101 µs |
| 最后机械位置（编码器） | 约22.30° |
| UART STATUS最高CTRL采样 | 12.4 rpm（非高速全程峰值） |
| CONTACT / RUNDOWN_ARMED | 0 / 0 |

零点 total 不等于 valid+reject 的一个差额保留板端原值，不重写统计语义。

状态日志：IDLE → PRECHECK → RUNDOWN_START → FAULT，最终 intent OFF、OUTCOME=FAILED。
运行反馈显示多次短暂运动后速度回落，没有达到持续 motion-established 条件；因此未 arm，也未进入 CONTACT/TIGHTEN。
未覆盖有负载完整工艺链，不能宣称完整流程、扭矩或速度跟踪通过。

## 停机原因的证据边界

首故障快照：domain=2、fault_reason=3、protection_flags=4。
对应当前源码 `FOC_DIAG_PROTECTION` / `FOC_FP_HEALTH` / `CL_BAD_ADC`。
这不是“4 A过流”，也不是50µs deadline miss。
`adc_fault=0`，`cl_late=0`；停住后 `cl_seq=injected_seq_count=192214`，
`cl_fault_last_us=9720580`，`cl_off_us=9720598`。
这些是锁存/停止后的证据，**不能证明故障瞬间每个health分支的值**。
ADC健康检查包含成对序列/新鲜度等路径，当前收据不足以确定具体是哪一个子条件触发，禁止仅凭RAW=1586/1599归因电流毛刺或电流过大。

另外发现候选的原因镜像顺序问题：`IntentPort_Fault()` 首先将“busy且session不再RUNNING”映射为TIMEOUT，
然后才检查已锁存底层首故障。硬件保护先停session后，可能因此遮蔽真正首原因。
故本次 EVT FSM `FAULT_REASON=TIMEOUT` 不能取代上面的底层 HEALTH/CL_BAD_ADC 首故障。
这属于待修的故障原因呈现/排序问题；本轮**没有修改**固件来重试。

## 收尾

STOP及ANALOG SAFE回读通过，SD=0、MOE=0、FOC=0；调试器再次关输出并halt，保存匹配Flash/RAM。
失败无自动重试。人工确认12V关闭后，仅执行原B启动选择恢复，停在B入口，不运行B应用或启动电机。
恢复收据：`tmp/intent-fsm-restore-1792411771441596600.json`。完整回读确认A/B应用、bootloader、私有区未变，仅启动元数据更新为B729，pending=0、attempts=0。
