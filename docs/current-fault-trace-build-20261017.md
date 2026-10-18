# Fault trace 构建整理及 FOC timing 待验收（2026-10-17）

## 最终状态

A/B 正式配置和 A/B 诊断配置均已链接通过。没有刷板、连接调试器、复位、
修改启动选择或启动电机。新增插桩后的 MCU timing **尚未重新测量**，不能声称已通过 50 us。

| 配置 | Flash 已用 / 229376 B | Flash 剩余 | RAM 已用 / 131008 B | RAM 剩余 |
|---|---:|---:|---:|---:|
| A 正式，trace OFF | 228940 B | 436 B | 127944 B | 3064 B |
| B 正式，trace OFF | 227924 B | 1452 B | 127928 B | 3080 B |
| A diagnostic，trace ON | 229316 B | **60 B** | 128752 B | 2256 B |
| B diagnostic，trace ON | 228300 B | 1076 B | 128736 B | 2272 B |

正式配置指当前 `ProtectedPipelineClosedLoop`，不是切回历史控制实现。
A 诊断版从 229852 B 降到 229316 B，节省 **536 B**，解决原 476 B overflow。
余量仅 60 B，不是宽裕的长期容量预算。B 同样节省 536 B。
RAM 数值含链接器既有 heap/stack 预留，不是运行时栈峰值证明。

## 开关

`firmware_common/foc_current_fault_trace.h` 明确默认：

```c
#ifndef FOC_CURRENT_FAULT_TRACE_ENABLE
#define FOC_CURRENT_FAULT_TRACE_ENABLE 0
#endif
```

仅接受 0/1。两个应用 CMake 选项均默认 OFF；正式预设明确 OFF；
`CurrentFaultTrace` 预设独立 ON。CMake 对实际目标定义数值 0/1，
而不是仅凭宏是否存在判断。旧的 `FOC_CURRENT_FAULT_TRACE` 不再是启用开关。

关闭时不编译 trace 模块；即便单独把该 .c 以默认值或显式 0 编译，也不会产生
记录器数据/函数符号。正式 ELF 经 nm 验证无 trace 环符号，正式 BIN 和原 pinned
A/B 镜像逐字节一致。没有覆盖原 pinned 镜像。

## 节省了什么，没有删什么

1. 不再在通用、广泛内联的 `FocFp_Trip` / `FocFp_TripTimeout` 中重复插入记录调用。
   改在物理 pair 的实际保护结果出口、判别后故障出口和 Take 故障出口记录。
   `ProtectedLoop_EmergencyOff` 保留一个冷路径钩子，放在原有功率关闭和 Trip 之后。
2. 诊断构建中，`FocFeedbackSafety_Poll` 共享一份 `noinline` / `-Os` 包装器，
   主体检查、赋值和返回原样；`FocFp_Trip` 同样共享冷包装器。
   正式构建仍使用原来的 inline/O2 实现。没有改变判据，但诊断编译会改变执行成本，
   必须重新实测，不能沿用旧版耗时。
3. 诊断构建把早期 Poll 故障的记录出口与 raw protection 的记录出口共用，
   仍然先保护、故障则返回、否则才调用判别器。没有跳过任何保护调用。
4. 新增 trace .c 单独 `-Os`，控制数学调用者仍保持原优化配置。
   已检查真实 compile commands：`-ffunction-sections`、`-fdata-sections` 均启用；
   链接 `--gc-sections` 启用，没有为了容量改 linker 分区。
5. trace 模块没有 printf、UART、格式化字符串、lookup table 或动态内存。
   人类可读输出仍全部在 Python。未通过删字段或缩窗口换容量。

最终版本没有保留试验过的额外 RAM relocation、强制寄存器内联汇编约束、
`-Oz` 或自定义数据分组；记录器继续使用普通 Flash 代码和 `.bss` 数据。

仍为 **16 帧 × 52 B**，帧布局、字段名、字段偏移与 Python schema 均未改变。
环头 28 B、帧区 832 B，环对象 860 B，ARM 活动指针 4 B，直接存储总计 864 B。
诊断版相对正式版的实际链接 RAM 增量为 **808 B**：直接存储增加 864 B，同时
共享包装器后的 RAM 执行代码/对齐合计减少 56 B；不是删除了 56 B trace 字段。

触发/冻结行为保持：首次非确认→CUR_CONFIRM 触发，故障立即冻结，
确认恢复后继续四帧再冻结；不自动 rearm。fault return 前记录实际状态，
未调用判别器的帧仍为 `DISC_EXEC=0` / `NOT_EXECUTED`。

没有修改 FOC、PI、SVPWM、保护阈值、CUR_CONFIRM、TWO_SAMPLE、PWM pipeline、
ADC/PWM 频率、触发点、IRQ 优先级或 A/B 逻辑。输出关断先于冷路径诊断。

## 验证

构建与测试入口：`python tools/current_fault_trace_offline.py`。
本轮 **54 项离线测试通过**（含板测工具的 mock 测试，不是新的实物测试）。

新增/加强检查包括：默认/显式 0 完全移除 trace、非法宏值拒绝、开关与 ELF 符号匹配、
实际编译/链接 section flags、诊断 ON/OFF 保护状态及返回值等价、环顺序/序号回绕、
故障提前返回、判别器故障后的冻结、Take freshness 故障冻结、恢复后四帧和已有控制回归。

无新增源代码或构建 warning，无构建 error。既有 unused-function/variable 和
链接 RWX warning 仍存在；没有通过关闭 warning 来掩盖。增量构建未打印某 warning
不代表该 warning 已消失，收据同时保存基线 warning 与差分检查。

机器可读收据：`tests/current_fault_trace_build/receipt.json`；各配置/测试日志同目录。
诊断输出：`foc2_app_a/build/CurrentFaultTrace/foc2.elf/.bin` 和 B 同路径。

## 50 us 后续实测边界

本轮遵守“不刷板、不启动电机”。现有 `ProtectedLoop_AdcProfileEnd` 的外层 DWT
测量没有移位；Begin/Protection/Discriminator/End 及共享 guard 包装器仍在其计时范围内。
原 deadline 计数、actual CCR late/margin 统计保留，没有提高 deadline 或关闭超时保护。

后续人工安排功率关闭测试时，应核验镜像身份、SD/MOE 关闭及 U/V/W 动力线断开，
不发送 START；读取新镜像的 wall max、deadline_miss、actual CCR late/margin。
只有新板端结果才可判断 `wall_max < 50 us` / `deadline_miss=0`。
本次没有这样的实物数据，也没有新的 fault trace，电流性质仍不能下结论。

trace build 已整理，等待功率关闭条件下重新板测 FOC timing
