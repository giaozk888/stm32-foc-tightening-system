# 固定 +0.45 A：约 32 ms 超速停机，未完成 5 秒测试

2026-10-19，用户明确重试并确认驱动板正常供电、无报警；沿用已确认的空载固定、12 V / 电源限流 0.5 A 与可立即断电条件。
仅执行一次手工固定 +0.45 A 请求，不自动重试/升流/关闭保护。

## 精确镜像与收据

- A profile：`Torque450mAFiveSecondDiagnostic`，UART 115200；本次波特率已匹配。
- A BIN SHA-256：`d96586bd785023ab066b4ac5814978eb35659f383ef9e5bc433d4edc59cc483f`。
- A ELF SHA-256：`1079285d4f50029c6d2f64da1a10c683cd4da5de2317fc3994a6a1aeabeb763a`。
- 暂存：`tmp/torque450-stage-1792408109407683400.json`。
- 运行及匹配全 Flash/RAM：`tmp/torque450-run-1792408381563252400.json`。
- 文件解码：`tmp/torque450-run-1792408381563252400-analysis.json`，核验 BIN/ELF/Flash SHA 与 SRAM 符号布局后解码。

健康确认按原 A/B 正常流程完成，confirmed A720，无强制确认。
校准 valid=4000、reject=44、total=4045、max consecutive reject=1，zero U/V=1561/1564。
预检 FOC wall max=28.188 us、deadline miss=0、CCR late=0、min actual margin=16.658 us。

## 唯一一次固定 Iq 与停止原因

已发送且收到 `OK TORQUE450 QUEUED MANUAL_ONE_SHOT=1`；start_attempts=1。
IdRef=0、IqRef=+0.45 A，绕过速度/位置环；并非 20 rpm SPEED 指令。
板端 session 运行至约 31998 us 即进入 FAULT，flags=1024=`CL_OVERSPEED`。
原保护在滤波/控制速度超过 60 rpm 时关断；本次没有扩大或关闭该阈值。

| 首故障快照 | 值 |
|---|---:|
| 编码器位置 | +11.4697 mechanical deg |
| 瞬时速度 | +155.049 rpm |
| 滤波控制速度 | +62.2384 rpm |
| 本次速度命令 | 0（固定 Iq 模式） |
| IqRef | +0.4500 A |
| Iq | +0.52684 A |
| Id | -0.09657 A |
| Vq / Vd | +0.47926 / +0.08802 V |
| Vdq 模长 | 0.48728 V，未饱和 |
| encoder valid/errors | 1 / 0 |
| current validator / unresolved consecutive | TRACKING / 0 |

首故障快照是瞬时值，不可称为全程平均电流。终止帧已关断 gates，但仍保留最后电流/电压计算值。
本次未发生 hard-current、CURRENT_INVALID 或 CUR_CONFIRM fault；不能因此认为物理电流极性/电角零点已被独立证明。

## 运动证据范围

200 ms 间隔 trace 来不及覆盖完整动态，只保存约 0.989 ms 初始帧与 31.999 ms fault 帧。不能用两帧证明启动过程完全平稳。
另有现有约 1 kHz 全窗口 raw 运动摘要：

- 31 个 fresh observations，0.987..31.027 ms，最大间隔 1038 us。
- net=481 counts=+10.56885°；total raw absolute=485 counts=10.65674°（含抖动）。
- 正向变化 29 次、反向 1 次、stationary=0，最大正 excursion=481 counts、负 excursion=-2 counts。
- raw 约 8156→7675，方向沿用 -1；终止时 raw=7633，原 mechanical position=11.4697°。
- 最后一次 encoder delta=-42 / dt=992 us 换算约 +155.049 rpm，与快照瞬时速度一致；不是仅滤波字段跳变而 raw 未变化的情况。

结论仅为**编码器报告了明显正向运动并触发速度限制**。用户本轮尚未说明肉眼是否看见轴转动，不能把软件角度冒充独立实轴/转矩证明。
尤其本次没有运行满 5 秒，不能给出持续旋转通过结论，也不能据此断言相序或 electrical zero 已正确。

## 时序与停止恢复

- 最终 FOC wall max=29.3706 us，deadline miss=0；actual CCR late=0、min actual margin=10.9706 us。
- CUR_CONFIRM=46 enter / 46 clear / 0 fault。
- fault 后 SD=0、MOE/AOE=0、CCER=0，STOP/ANALOG SAFE ACK 成功；CPU halted，Flash/RAM 已保存。
- 用户随后确认 12 V 关闭，只恢复原 B 启动选择，在 B 入口前停住，不执行 B 应用。
- 恢复收据：`tmp/torque450-restore-1792408452283540300.json`；应用、bootloader、私有配置字节未变。
- 未再启动、未改保护/PI/相序/零点，不以超速为理由自动放宽速度阈值。

固定 Iq 没有速度调节器，空载一旦克服阻力可以继续加速；5 秒是最大 lease，不是保证必须运行 5 秒。现有超速保护优先停止，此次应保留该证据而非强制跑满。
