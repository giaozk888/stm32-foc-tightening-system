# 首次 5 秒电机实验：+0.10 A，批次已安全中止

用户在已完成 A696 功率关闭启动/计算验证后请求“启动电机”。按已授权的正负逐档计划启动，不重刷、不开 0.25 A，不改 PI、相序、电角零点或保护。

## 实际执行范围

- 先只读核对 MCU 原本停在 A696、完整 Flash 与成功验证收据一致、输出关闭。
- 复位同一已确认 A，重新完成零点、5 秒 MonitorTask 时序报告和静止准入。
- **只发送了一次 `MOTOR TEST BREAKAWAY POS 100 CONFIRM`**，收到 QUEUED ACK。没有发送第二档或负方向命令。
- 板端按 5000000 us 租约正常停止，状态报告 US=5000010、STATE=DONE、FLAGS=0、FAULT=0、SD=0、MOE=0、CCER=0、IqRef=0。
- 停机后的主机静止检查中止：三次位置读数为 0.68°、0.65°、0.76°，范围约 0.11°，超过本次既定 0.10°。这不是 hard-overcurrent 或 FOC fault；没有为继续测试而放宽判据。
- 批次随即 STOP、ANALOG SAFE、SWD 输出关闭并 halt，保存 Flash/SRAM。没有重试、继续升流、反转或刷板。

## +0.10 A / 约 5 秒的记录

| 项目 | 结果 |
|---|---:|
| 实际 IqRef | 所有保存驱动帧均为 +0.100 A |
| 保存驱动帧 | 25 帧，0.000989–4.806999 s |
| 停机 terminal | 5.000100 s，IDLE / gates=0 / IqRef=0 |
| 25 帧平均 Iq | +0.094580 A |
| 25 帧平均 Id / 平均 \|Id\| | +0.000539 / 0.005655 A |
| 25 帧平均 \|Iq\| | 0.095133 A |
| 25 帧平均控制转速 | 0.06929 rpm |
| 25 帧 Vdq max | 0.06344 V，无保存帧饱和 |
| 任务级 encoder 观测 | 5000 次，最大间隔 1046 us |
| 任务级净 encoder 位移 | +49 counts = +1.07666° |
| 相对首次任务观察最大正/负偏移 | +1.18652° / −0.02197° |
| FOC wall max | 28.81176 us |
| >50 us deadline miss / CCR late | 0 / 0 |
| actual CCR margin min | 2.57059 us |
| CUR_CONFIRM enter / clear / fault | 112 / 112 / 0 |

零点为 valid=4000、reject=46、total=4050、最长连续 reject=1，zero U/V=1560/1563。首故障 snapshot valid=0。

约 0.001 s 机械角为 0.0659°，0.201 s 已到 1.0547°；随后 0.4–4.8 s 大部分读数仅在约 1.05–1.16°附近变化。**这些读数没有持续单向旋转的证据。** Iq 均值接近参考、Id 均值很小，也不能据此证明实际转矩方向、电角零点或机械摩擦根因。

任务级原码绝对累计为 9835 counts（216.101°），包含每个外环观察的正反微小变化/编码器抖动；不能把它等同于转子真的走过 216°。低频关键帧的绝对角差累计只有 1.82373°，二者采样尺度不同，均须保留，不能混成同一个物理测量值。

## 本次暴露的诊断边界问题

离线正式分类保持 `INSUFFICIENT_DATA`，原因 `MISSING_OR_INVALID_FULL_WINDOW_MOTION`。不是缺少整个 5 秒采集，而是 aggregate 的 last_us=5000003，比现行严格 5000000 us 上限多 3 us；其余 count=5000、覆盖=4999016 us、bad_ref/gates/encoder=0、区间计数之和=4999 正常。

本轮没有修改该上限、保护或固件，也没有把记录时间强行截成 5000000 以制造 PASS。只补充离线工具在拒绝时仍输出原始 aggregate，防止错误上下文丢失，并用同次真实捕获添加回归。**不能宣称已经通过 CONTINUOUS_ROTATION 或测得 BREAKAWAY_IQ。**

主机中止的首个原因仍是停机静止检查；aggregate 边界问题是在停止后离线分析发现的第二个问题。即使将来修复记录边界，当前位移趋势仍需要单独判断，不代表这个档位就能稳定起转。

## 最终状态和证据

- MCU 停住，VTOR=A，DHCSR=0x30003；SD=0、MOE/AOE=0、CCER=0。BDTR 保留配置位，不是整个寄存器为零。
- Flash SHA 与本次之前验证完全相同：`df7c649c600ea750dfa8bc5e2b2384dcd7f5eef2b36503e5113741f815547f35`。启动选择仍为已确认 A696，B/bootloader/metadata/私有参数未改变。
- root：`tmp/breakaway5-batch-1792388286865682600.json`
- 单档：`tmp/breakaway5-batch-1792388286865682600-00.json`
- 同档 `-flash.bin` / `-ram.bin` 完整保留，仅本地保存。
- 离线解码：`tmp/breakaway5-first-motion-analysis.json`
- 启动前只读核验：`tmp/breakaway5-premotion-inspect-1792388271215665800.json`

相关 37 项离线回归通过，日志 `tmp/breakaway5-first-motion-tests.log`。本轮只新增离线诊断字段保留，不刷写任何新固件或改变测试阈值，不自动运行更多档位。
