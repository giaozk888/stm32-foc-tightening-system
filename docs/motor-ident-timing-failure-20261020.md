# Rs 辨识连续性退出：同一失败帧证据

## 本轮范围

仅新增诊断编译开关 `FOC_IDENT_TIMING_TRACE_ENABLE`（默认OFF）及独立A preset
`MotorParameterIdentificationTimingDiagnostic`，继承上一轮取消0.10度位移退出的镜像。
没有修改45–55us/seq+1判据、400ms限时、current discriminator、CUR_CONFIRM、PI、
SVPWM、PWM pipeline、IRQ或保护阈值。正常A/B不启用插桩，B文件及板端B字节保持。

`MotorIdent_Reference` 首次连续性失败时，在修改last_seq/last_us和STOP之前保存：
上一seq/us、本次seq/us、无符号delta_seq/delta_us、失败bitmask；先字段后valid。
绑定层再保存injected_seq、frame_seq、cl_last_us、上次/本次hold计数及判别path，
经DMB后发布独立context_valid。后续不覆盖，人工复位才清零。
没有修改任务限时退出；任务限时而非连续性失败时，不伪造ADC失败快照。
ISR只有整数赋值/加减/比较与发布屏障；UART格式化仅停止后的前台命令。

新增只读命令：`MOTOR TEST IDENT TIMING`、`MOTOR TEST IDENT TIMING CONTEXT`。
新增Python `tools/motor_ident_timing_report.py`，校验同会话ELF/RAM哈希、1724B ABI、
差值和bitmask一致性；旧1660B镜像不可解码为新快照。实际板测适配器还逐字段核对UART与RAM。

## 构建与离线验证

- A diagnostic BIN214156B，Flash214156/229376B，RAM130720/131008B（链接余量288B）。
- 新插桩增加64B RAM，Flash相对前一候选增加576B。保留原任务栈/堆预留。
- BIN SHA256 `ecb4b77584e4d589f2881719a1741907335b2e2264d480ee16b815385d9e899c`。
- ELF SHA256 `19c5654714df2a9abf641d94f891fee8425ac181c1ae7155073efba66f8faf49`。
- 编译通过，已有unused/RWX warning集合与上个NoTravel构建一致，无新增warning类别。
- 29项相关离线测试通过。新测试覆盖边界45/55、44/56、seq跳变、计数回绕、
  首失败不可覆盖、STOP前上下文、停止后UART、解码完整性、实际控制函数冻结及镜像基线。
- 日志：`tmp/motor-ident-timing-build.log`、`tmp/motor-ident-timing-all-tests.log`。

## 人工授权后的单次板测

用户分别确认12V OFF、锁轴台架夹具/外壳固定/防护/接线不变；授权仅非活动A。
完整回读后再确认12V ON、0.5A限流、无报警、现场可立即断电。

- stage `tmp/motor-ident-rs50-stage-1792499227646388800.json` PASS。
- run `tmp/motor-ident-rs50-run-1792499287893157400.json`。
- 校准/时序预检通过。只发送一次 `MOTOR TEST IDENT RS 50 LOCKED CONFIRM`。
- 没有START、自动重试、升流、Ld/Lq或PI参数写入。

| 同一失败上下文 | 值 |
|---|---:|
| previous accepted seq | 157402 |
| previous software timestamp | 7988404 us |
| current seq | 157404 |
| current software timestamp | 7988504 us |
| delta seq | 2 |
| delta time | 100 us |
| flags | 5 = seq非+1、dt>55 |
| current injected seq / accepted frame seq | 157404 / 157404 |
| cl_last_us | 7988504 us |
| hold before / now | 532 / 533 |
| current path | 1 = NORMAL |
| snapshot valid / context valid | 1 / 1 |

UART与RAM全部一致。判别器在两次进入辨识reference owner之间hold了1帧；
恢复后下一有效帧seq跳2、软件dt100us，触发辨识自身严格连续性判据。
**本次原因是辨识把“判别后有效帧连续”当成“原始ADC每拍连续”的接口语义冲突。**
这不等价于FOC超时，也不能据此声称物理ADC丢样或硬件触发间隔异常。
这里时间戳来自ProtectedLoop_Pair中软件取时，不是ADC aperture。
前两轮未保存失败快照，因此不能把本次证据倒推为前两轮的确切原因。

本次在开始后10205us退出：MID_TIMING8、N0。
参数样本电流reject7、good196、max reject run2，未触发连续3对或累计17对退出。
这些估计器current reject与原current discriminator的hold是不同统计，不应混为一谈。

| 运行保护/时序 | 结果 |
|---|---:|
| FOC max | 34.8118 us（含插桩） |
| deadline miss | 0 |
| actual CCR commits | 133348 |
| actual CCR late | 0 |
| actual min margin | 15.0471 us |
| CUR_CONFIRM enter/clear/fault | 53/53/0 |
| 原fault valid / ADC fault / FOC fault | 0/0/0 |

稳态采集窗口200ms尚未到达，N0，不输出Rs结果。
先STOP/ANALOG SAFE再读日志并停住MCU；用户确认12V OFF后恢复原B启动选择。
恢复收据 `tmp/motor-ident-rs50-restore-1792499463782223100.json` PASS：
confirmed B820、pending0，SD/BDTR/CCER均0，MCU停在B入口。
B/boot/private及A候选字节未变，不执行B应用、不再注入电流。

## 下一步（本轮未实施）

Rs稳态offset/均值估计可考虑跳过判别器hold的样本，但继续记录gap且维持异常预算/总时限；
Ld/Lq瞬态拟合则仍必须要求可验证的连续原始时基，缺点不得插值或假装连续。
应区分两种辨识的数据质量要求，而不是放宽正常FOC或current discriminator保护。
所有更改需另行实现/离线验证，本轮只定位，没有放宽连续性门槛。
