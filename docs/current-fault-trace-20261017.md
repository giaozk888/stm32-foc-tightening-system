# 电流保护连续短窗口诊断（2026-10-17）

> 本页为首轮实现记录；A 槽容量问题已在后续构建整理中解决。
> 最新开关、四配置占用与回归结果见 `current-fault-trace-build-20261017.md`。

## 状态与范围

只增加观察记录，没有修改保护阈值、CUR_CONFIRM、TWO_SAMPLE、PI、PWM
pipeline、控制数学、采样频率/触发、优先级或 A/B 启动逻辑。没有连接调试器、刷板、
复位、改变 B 启动选择或发送 START。本次没有新的实物故障窗口，结论为 **D：证据不足**。
不能凭上一轮末帧的 V=-605 counts 判断真实电流或采样干扰。

当前实际使用的 A 镜像对应配置也进行了编译，但诊断配置 **链接失败：超出 A 槽
476 bytes**。B 诊断配置可以链接。不能把 B 的通过当成 A 的通过，不能把失败链接
目录下的残留文件用于刷写。没有扩大分区或删除其他功能来回避这个错误。

## 修改位置

| 文件 | 本次增加的内容 |
|---|---|
| `firmware_common/foc_current_fault_trace.h/.c` | 16 帧环、进入/比较/保护/判别/PI/PWM/结束记录接口 |
| `firmware_common/foc_feedback_safety_candidate.h` | Push 开始记录，保护返回前记录，实际判别器调用后记录；结构体只增加类型标签，布局未变 |
| `firmware_common/foc_filtered_protection_candidate.h` | 使用已有比较中间量；现有 Trip/TripTimeout 状态写完后记录故障；不改变原返回顺序 |
| `firmware_common/protected_adc_irq.inc` | 原有计算/冻结路径完成后结束当前帧，仍包含在现有外层 DWT wall 测量中 |
| `firmware_common/foc_pwm_pipeline_binding.inc` | 新 pending 确实生成成功后记 PWM 更新标志 |
| `foc2_app_a/Core/Src/main.c`、B 同名文件 | 在原 PI 积分更新前记录实际到达，不改运算或调用顺序 |
| 两个应用的 `CMakeLists.txt` / `CMakePresets.json` | 默认 OFF 的诊断开关与 `CurrentFaultTrace` 预设；只让新增记录器源文件用 `-Os` |
| `tools/current_fault_trace_report.py` | 离线按时间顺序解码，核对 ELF/BIN、完整 Flash/RAM、运行槽 VTOR |
| `tools/current_fault_trace_offline.py` | 隔离构建、检查原镜像字节一致、内存/容量收据、离线回归；不操作硬件 |
| `tests/test_current_fault_trace.py`、三个 `foc_current_fault_trace_*` C 测试文件 | 环回绕、先保护后判别、冻结、恢复后四帧、真实 IRQ 包装器、开关等价性 |

这里列的是本次诊断增量，工作区还存在此前未提交的修改，不应把整个 git diff 当成本次修改。

## 存储与字段语义

- 16 帧，每帧 52 bytes，帧区 832 bytes。
- 环头 28 bytes，环对象 `foc_current_fault_trace` 合计 860 bytes。
- 活动帧指针在 ARM 上 4 bytes；直接静态诊断存储共 **864 bytes**。
- B 链接 RAM 从 127928 增至 129296 bytes，实际增加 **1368 bytes**。
  除上述 864 bytes，还包括调用处 RAM 执行代码增加的 504 bytes。
  RAM 区域为 131008 bytes，剩余 1712 bytes（链接计算含既有 heap/stack 预留，
  不是运行时栈峰值证明）。
- B Flash 从 227924 增至 228836 bytes，增加 912 bytes，剩余 540 bytes。

记录 raw U/V、offset U/V、保护已经计算出的有符号 U/V/W counts、实际 count limit、
比较是否执行、过限相位位图、CUR_CONFIRM active/cycles/good_samples、保护结果/原因、
判别器实际是否执行及返回值、PI/PWM 更新路径是否到达、CCR1/2/3、现有预测电角度、
TIM1 CNT/DIR、序号和现有时间戳。

电流符号为 `offset-raw`，W 为 `-(U+V)`。**没有 ADC-W / offset-W 数据**，输出 NA；
sector 也无现成字段，输出 NA。不在 ISR 里额外做 ADC→A、扇区或采样相位计算。
离线表中的 abs U/V 由已记录的有符号 counts 计算，不增加实时负担。

CCR 是这一对 ADC 进入保护处理时的 **preload 寄存器读回**，不是 active shadow
锁存值，也不是本拍即将生成的 pending。CNT/DIR 同样是处理时刻，不是 ADC 触发
瞬间。不能据此单独证明某开关沿造成干扰。

`pi_frozen=1` 表示本拍未执行正常 PI 积分更新；原 READY 路径可能仍按旧逻辑清零积分。
`pwm_frozen=1` 表示本拍未生成新 pending；**不代表 IRQ 入口没有提交上一拍 pending**，
更不代表门极必然关闭。没有改变一拍 pipeline。

## 触发、冻结和顺序

平时每个进入反馈保护核心的物理 ADC pair 滚动写一帧。只在首次非 pending→pending
时标记 trigger，不立即冻结；现有 CUR_CONFIRM 的进入帧记 cycles=0，之后最多四个
新 pair 消耗既有周期预算。这一点未改。

保护故障时先写当前状态/原因、fault seq/index，再发布 frozen，后续不再覆盖。
保护提前 return 的帧，`DISC_EXEC=0`、`DISC_RESULT=NOT_EXECUTED`，不继承上一帧。
只有真实调用 TWO_SAMPLE 后才写 `DISC_EXEC=1` 和其原始返回值。

确认恢复时标 RECOVERY；恢复帧后再保留四个 pair，由 End 冻结。
若此期间出现保护故障则立即故障冻结。未增加任何停止/清故障/使能动作。
故障时和恢复冻结时，在发布 frozen 前包含内存屏障；仅分析冻结环或 MCU 已停住的捕获。

16 帧足以保留四帧前史、触发帧、随后最多四个确认周期和恢复后四帧；
启动不足四帧时不能凭空生成前史。重启可重新记录，没有运行中自动重装或覆盖首窗。

**首次触发可能发生在启动前的 READY/零电流检查。** 此时恢复窗口已经冻结，
不能声称它捕获了随后 START 的故障。以后若专门捕获 START，必须在人工安排的
输出关闭阶段明确重装诊断，或调整测试的捕获起点；本次没有增加自动重启或清环命令。

## 高频开销和计时

新增工作为静态指针检查、固定字段赋值、五次 TIM1 寄存器读取、环索引递增、少量
整数标记比较、复制现有浮点角度（无新增角度运算）、冷路径冻结屏障。
没有循环、格式化、UART、printf、动态分配或重复电流浮点换算。
冻结后钩子只走指针/冻结检查。

现有外层 DWT wall 计时仍包含新钩子；离线报告读取原 `cl_current_cycles` 的
wall_max/deadline_miss。**本次没有新 MCU 测量，不能把旧版 28.85 us 移用为诊断版结果，
也不能宣称新增插桩后仍通过 50 us。**

## 离线读取

以下工具仅读取已有文件，不连接板子：

```powershell
python tools/current_fault_trace_report.py --elf foc2_app_b/build/CurrentFaultTrace/foc2.elf --ram CAPTURE_RAM.bin --flash CAPTURE_FLASH.bin --vtor 0x08040000
```

要求同一次采集的完整 RAM（131072 bytes）、Flash（524288 bytes）以及实际 VTOR。
工具核对该槽 Flash 与 ELF 同目录 BIN 一致、环对象布局与地址，然后从
`(write_index-count)&15` 起恢复时间顺序，检查 seq 连续，输出 PRE/TRIGGER/CONFIRM/
FAULT/RECOVERY/POST。测试用合成数据不是新的实物证据，不在报告中伪装板测表格。

## 构建与回归

运行 `python tools/current_fault_trace_offline.py`，收据在
`tests/current_fault_trace_build/receipt.json`，逐配置构建日志和八组回归日志也在该目录。
脚本在 A 容量失败时最终返回 2，不掩盖该失败。

本次八组共 **53 项离线测试通过**（包括工具/板测脚本的 mock 测试，不是实物测试）。
新增六项 trace 测试在 `-Os`/`-O2` 下验证核心、真实 ADC IRQ 包装器、连续顺序解码、
保护/判别调用顺序以及诊断 ON/OFF 的保护核心状态等价；合成序列不能证明模拟硬件信号。

B 诊断 BIN SHA256：`5a693a7919524c06562c980dd2cb3e90750d850230c1dda109326716995976e4`。
ELF SHA256：`2e87f087225600b968073d5f6220fe41f0c7357ad2c562899c3da88bfad6aeb1`。

诊断 OFF 的 A/B 隔离重建 BIN 与原 pinned 闭环镜像逐字节相同，原镜像没有覆盖。
新增诊断 C 与调用处做基线差分 warning 检查；既有 unused-function/variable 和
链接 RWX warning 尚存在，不能声称整工程零 warning。

本轮停在代码/构建/离线证据；A 容量问题尚未解决，B 可链接也不等于实机通过。
没有新的连续实物窗口，分类保持 **D：证据不足**，等待人工决定后续构建容量处理与上板验证。
