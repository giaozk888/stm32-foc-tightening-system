# Stage 7.12：PC4/PC5 ADC2 采样时间 A/B 对照

## 目的

检验把 PC4/PC5 的 ADC2 常规采样时间从 47.5 延长到 247.5 ADC cycles，是否消除 12 V、停桥状态下的孤立尖峰。只修改 A 槽诊断固件，B 槽保留 Stage 7.11 的 47.5-cycle 基线。`ANALOG VOLT` 仍使用首次原始读数；三取中值未进入保护或电机控制。

## 修改与验证

在 `foc2_app_a/Core/Src/main.c` 中，`ADC_ReadRegularMedian()` 启动快照阶段仅为 ADC2 的 PC4/CH5 和 PC5/CH11 选择 `ADC_SAMPLETIME_247CYCLES_5`；运行时 `ADC_AnalogLiveReadChannel()` 使用相同档位。ADC2 电流采样 CH2 和 ADC1 保持原采样时间。必须在注入转换启动前设置 PC4/PC5 采样时间，不能只修改注入转换已启动后的运行时配置。

A 构建成功：FLASH 225116 B / 224 KiB，RAM 65080 B。用 `tools/transfer_iap_stream.ps1` 从已确认的 B 写入 A：225116 B、CRC32 `0xF3F00847`，`FW END ... ATTEMPTS=2 RESETTING`。A 自动确认 `GEN=230`，无故障；重新进入 `ANALOG SAFE`，软件检查 `SD=0 MOE=0 FOC=0`。所有比较在同一约 12 V 供电、IDLE、SAFE 条件下进行，均运行约 120 秒。

## 数据

| 条件 | 通道 | 新增三采样组数 | 组内极差 >60 counts | 比例 | 最高单点 | 最高三取中值 | ADC 错误 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B：47.5 cycles | PC4/VBUS | 1216 | 44 | 3.62% | 1429 | 603 | 0 |
| A：247.5 cycles | PC4/VBUS | 1217 | 28 | 2.30% | 1372 | 752 | 0 |
| B：47.5 cycles | PC5/VTEMP | 1215 | 44 | 3.62% | 2344 | 1368 | 0 |
| A：247.5 cycles | PC5/VTEMP | 1216 | 43 | 3.54% | 2181 | 1394 | 0 |

在 A 条件下，PC4 最高中值 752 对应三元组 `752,576,778`，按 3.28 V、25 倍分压换算约 15.1 V；但供电物理设置约 12 V。这是两个读数偏高、三取中值也偏高的例子。

## 判断

- PC4 异常频率在这两轮测试中降低约 36%，但每种条件只有一次短时运行，不能据此断定延长采样时间解决了问题；尖峰仍存在。
- PC5 异常频率几乎未变化，因此单纯采样建立时间不足以解释两路异常。共享模拟电源/参考、地、ADC 时序或驱动板模拟输出耦合仍需区分。
- 三取中值不能保证滤除异常，不应直接用于过压保护；现有 `ANALOG VOLT` 仍为原始首次读数且 `PROTECT=0`。

## 下一步建议

优先在 12 V、停桥条件下做低阻抗输入隔离对照：全部断电后，断开 PC4/PC5 到 PD6010B 的信号线，分别经 4.7–10 kΩ 电阻接到 NUCLEO AGND；复电确认 A 已确认和 SAFE 锁存，再用 `tools/analog_pc4_pc5_compare.ps1 -Port COM5 -ExpectedSlot A -Seconds 120` 测试。注意：此时 PC4 接地，原 `analog_safe_smoke.ps1` 的 12 V 母线估值检查必然失败，不能把它当成板子故障。若不具备电阻或不熟悉 AGND 引脚，先不要改线。B 槽保留 47.5-cycle 基线固件。
