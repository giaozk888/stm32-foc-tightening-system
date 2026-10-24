# Rs gap-admission候选：单次50mA板测

本轮按用户请求上板，分别取得OFF/锁轴夹具/外壳固定/防护/原接线/12V限流0.5A、
ON无报警/现场可立即断电的确认。仅非活动A，保留原B。没有START、自动重试、升档或L测试。

## 版本与证据

- preset `MotorParameterIdentificationRsGapDiagnostic`；BIN214452B，ABI1740B。
- BIN SHA256 `9f0bf902af96699fde1d817b486588a228b71e830a291ffb49cf5f015f220676`。
- ELF SHA256 `5f1fb840e744ed20a6935183902d902405e7266498384ef7a667b28e741e3e2a`。
- 新独立pin runner `tools/motor_ident_rs_gap_board.py`，精确B820基线、同会话镜像/ELF、
  UART/RAM timing及gap统计逐字段比对。旧runner/pins不改。
- 3项新脚本测试通过，全部motor-ident相关36项通过：
  `tmp/motor-ident-rs-gap-board-regression.log`。
- stage `tmp/motor-ident-rs50-stage-1792499893114031600.json` PASS：
  完整独立回读，原B/boot/private/metadata不变。
- run `tmp/motor-ident-rs50-run-1792499947946540500.json`。

## 本次失败快照（UART与RAM一致）

校准和时序预检通过，只发送一次 `MOTOR TEST IDENT RS 50 LOCKED CONFIRM`，明确ACK。
终态MID_TIMING8，N0，没有参数结果。

| 字段 | 值 |
|---|---:|
| start_us | 7992290 |
| prev_seq / seq | 157480 / 157481 |
| prev_us / us | 7992295 / 7992352 |
| delta_seq | 1 |
| delta_us | 57 |
| flags | 4，仅dt>55 |
| adc_seq / frame_seq | 157481 / 157481 |
| hold_before / hold_now | 534 / 534 |
| 判别path | NORMAL |
| Rs gap events / skipped / max | 0 / 0 / 0 |
| current reject / good / max run | 0 / 1 / 0 |

距开始约62us退出，未达到200ms稳态记录窗口。
**这次是仍保留的seq+1帧软件时间差45–55us检查失败，不是hold gap失败。**
新缺帧接纳分支尚未在本次运行中触达，因此不能声称板测已通过该功能。

当前source_us由ProtectedLoop_Pair中AS5047P_DmaNowUs软件取时，
在ADC IRQ入口pending commit等工作后；不是ADC硬件采样孔径时间。
首拍pending无效、后续提交有效pending时的执行路径差异可能改变取时间隔，
但本轮未锁存入口/commit阶段时间，不能认定57us必然由此造成。
seq连续且ADC MISS0/PF0，没有证据证明物理ADC丢样或频率改变。

| 运行时序/保护 | 结果 |
|---|---:|
| FOC max | 30.6882 us |
| deadline miss | 0 |
| actual CCR commits | 133430 |
| actual CCR late | 0 |
| actual min margin | 16.6471 us |
| CUR_CONFIRM enter/clear/fault | 44 / 44 / 0 |
| 原保护fault/adc_fault/foc_fault | 0 / 0 / 0 |

本轮未修改固件/阈值以继续尝试；执行后STOP/ANALOG SAFE，保存RAM/Flash并停住。
用户确认12V关闭后，仅恢复原B启动选择，不执行B应用。恢复结果见
`tmp/motor-ident-rs50-restore-1792500005710633900.json` PASS：
confirmed B824、pending0，SD/BDTR/CCER均0，MCU停在B入口，原B/boot/private及A字节不变。

## 后续建议（本轮未做）

Rs稳态准入应进一步区分“ADC硬件时基完整性”与“软件取时抖动”，
不宜把软件时间戳误当50us精确采样孔径。保持原ADC freshness/watchdog与时限独立，
再为Rs定义经过证据支持的质量检查；Ld/Lq则仍需独立硬件时基/latch证明。
不可仅把55us随意加大并声称解决，也不可把本次N0解释为有效Rs。
