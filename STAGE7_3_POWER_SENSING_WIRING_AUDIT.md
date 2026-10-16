# Stage 7.3 — PD6010B 母线/温度接线与 ADC 只读采样验证

当前进度：`VBUS→PC4`、`VTEMP→PC5` 已接线；有上电快照、IDLE 状态下约 10 Hz 的只读采样，以及利用 ADC1 `VREFINT` 工厂校准值换算的电压估算。当前 A 槽已确认，B 槽保留上一版只读采样固件作为回退。**尚无电机运转时采样，也无欠压/过压或过温保护。**

## 手册与实物核对

《Genbotter 无刷电机驱动板用户手册》图 2-7 给出两个模拟输出：

- `VBUS = POWER / 25`。`POWER` 是驱动板防反接器件后的母线，不一定与外部电源端 `VIN` 完全相同。按 12 V 粗算，`VBUS` 约 0.48 V；这不是实测值。
- `VTEMP = 3.3 V × 4.7 kΩ / (R_NTC + 4.7 kΩ)`。25 °C、标称 10 kΩ NTC 时约 1.06 V；没有 NTC 的 B 值/校准点，暂时不能把电压可靠换算成温度阈值。

图 2-8 的 24 针控制/采集示意将 `VBUS` 标为 8 脚、`VTEMP` 为 15 脚、`GND` 为 7/16 脚、`CTRL_SD` 为 24 脚。手册不同段落对接口编号使用了 CN1/CN3/CN4，存在互相矛盾的编号；**接线以实物丝印、明确的信号名和断电导通核对为准，不单凭接口编号或图示方位插线**。手册提到的备用 10 针接口也含 VBUS/VTEMP，但本次没有确定用户当前具体走哪一个接口。

## 初始固件核查（接入前）

- ADC1 PA0 读取 `AMP_IU`，ADC2 PA1 读取 `AMP_IV`，20 kHz 注入转换供电流环使用。PC3 虽被初始化成 ADC 模拟脚，但项目注释明确保留给 `AMP_IW`，当前未采样，不应擅自改接 VBUS。
- PC6 是 `DRIVER_SD`；PC10/PC11 是 USART3 的 Modbus TX/RX，不是模拟采样。
- 当前没有 `VBUS` 或 `VTEMP` 的 ADC 采集和故障判定。`FOC_DC_BUS_V = 12.0f` 是 FOC 电压到 PWM 占空比的固定计算参数，不是母线测量值，因此不能用于欠压/过压保护。
- Stage 7.1 `SELFTEST READY=1` 与 Stage 7.2 的 ADC/FOC 链看门狗都不覆盖母线欠压/过压和温度。

## 接入前的现场检查

最初审计时 `VBUS`、`VTEMP` 尚未接到 STM32G474；后续已按下文接线并完成上电快照验证。不能将当前诊断视为已实现的运行保护。

### NUCLEO-G474RE 板卡手册 UM2505 核对

用户提供的 ST UM2505 Rev 7（表 10、12、16、17）明确：

- PC4/PC5 在本工程源码中空闲，但板卡默认分别经 SB13/SB19 接到 Arduino D1/D0（USART1 信号路径）；板载 ST-LINK 虚拟串口默认走 PA2/PA3 的 LPUART1，**不是** PC4/PC5。
- PC4 可在 ST Morpho `CN10-34` 引出（默认 SB33 ON），PC5 可在 `CN10-6` 引出（默认 SB3 ON）。这些是排针映射，不代表其 ADC 功能已经证实。
- UM2505 的表 17 把 PC4/PC5 只标作 I/O，没有列出它们的 ADC 通道。该表不是 MCU 全部复用功能表，故不能仅凭这张表断言 PC4/PC5 一定不能采 ADC；也不能据此把它们当成已确认的 ADC 输入。
- 手册列出的 Arduino 模拟输入 PA0、PA1、PA4、PB0、PC1、PC0，在当前工程中分别用于两路相电流、编码器 CS、PWM、PWM、PWM，没有可以直接接入的两路。

**当时结论：PC4/PC5 “程序空闲”已证实，但 ADC 映射待确认。以下 CubeMX 截图已解决该待确认项。**

### 2026-09-24：CubeMX 引脚截图补充确认

用户给出的 STM32G474RE CubeMX 功能菜单明确显示 `PC4 = ADC2_IN5`、`PC5 = ADC2_IN11`。因此上段的 ADC 映射待确认项已解决。预定连接为 `PD6010B VBUS → NUCLEO PC4 / CN10-34`、`PD6010B VTEMP → NUCLEO PC5 / CN10-6`，以及驱动板**信号地**与 NUCLEO `AGND / CN10-32` 共参考（先检查现有电流采样是否已共地，不重复制造多点地环路）。断电接线前核对实物丝印及 SB33/SB3 导通；绝不把 12 V `VIN` 接到 ADC。

两路均在 **ADC2**，而当前 ADC2 注入通道 IN2 正以 20 kHz 采 `IV`。后续低频实时采样须确认规则转换不会破坏注入采样时序与 FOC 计数；不能直接把已验证的上电快照当作实时保护。用户先前测得驱动板侧 `VBUS ≈ +0.47 V`、`VTEMP ≈ +1.16 V`；接线后以 NUCLEO AGND 为参考复测结果见下文。

### 上电一次性原始值诊断：A 槽已烧录并验证

用户已将线接上，并确认线序为 `VBUS→PC4`、`VTEMP→PC5`。首次电压记录顺序有歧义；随后以 NUCLEO AGND 为参考逐引脚复测，确认 `PC4=0.48 V`、`PC5=1.11 V`，与接线和驱动板信号定义一致。

A/B 源码已加入 `ANALOG BOOT` 诊断：静态电流零点校准后、20 kHz 注入转换启动前，将 PC4/PC5 设为模拟输入，分别用 ADC2 规则通道 IN5/IN11 读取中值；命令只返回 `PC4_RAW`、`PC5_RAW` 和 `VALID`，`LIVE=0` 提醒它是上电快照。不会在电流环运行中再次调用带 `HAL_ADC_Stop()` 的读取函数，不改变 START/保护阈值。A/B 编译通过：A Flash 218,652 B / RAM 64,864 B；B Flash 218,340 B / RAM 64,848 B。

2026-09-24 使用已确认的 B 槽 `GEN=203` 通过 IAP 升级 A 槽，镜像 218,652 B，CRC32 `0xAFC8FB34`。首次执行使用 Windows PowerShell 5.1，因 `[Convert]::ToHexString` 不存在而在 `FW BEGIN` 后失败，异常处理执行 `FW ABORT`；复查 B 槽仍已确认、IDLE、预检通过。改用 PowerShell 7 后，`FW END` 返回 `TARGET=A ... ATTEMPTS=2 RESETTING`，A 槽自动健康确认。随后将传输脚本的十六进制转换改为 Windows PowerShell 5.1/PowerShell 7 均支持的 `BitConverter` 写法。

板上测试：`FW CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=206`；`SELFTEST READY=1 MASK=0x000`，ADC/FOC 计数在 200 ms 内各增长约 4500；`STATUS MODE=IDLE FLT=0`。命令 `ANALOG BOOT` 返回 `VALID=1 PC4_RAW=586 PC5_RAW=1410 ADC=ADC2 LIVE=0`。按标称 3.3 V 参考电压仅作粗估，约 0.472 V / 1.136 V，接近同点万用表 0.48 V / 1.11 V。未发送 `START`，未验证电机运动中的温度/电压采样。

上电快照只能证明接线/ADC 基础读数，不能作为实时欠压或过温保护。下面继续验证 IDLE 时的低频采样；保护阈值还需测量与校准。

### IDLE 运行中只读采样：B 槽已烧录并验证

新增 `ANALOG LIVE` 命令。低优先级 `MonitorTask` 每 100 ms 唤醒，仅在 `motor_control_mode=IDLE` 且无拧紧任务时，依次用 ADC2 规则组单通道软件触发读取 PC4/PC5。两路采样时间已在上电、注入转换启动前配置。运行中仅改变规则组的 rank 1，**绝不调用 `HAL_ADC_Stop()`**，因为它也会停止注入组的 IV 采样。每路用 `HAL_ADC_PollForConversion(..., 2 ms)` 有界等待；失败时置 `VALID=0`、增加 `ERRORS`，不把旧值当新值。命令报告原始值、样本数、错误数与数据年龄；超过 500 ms 标记为无效。活动电机状态下不采样、不作为保护依据。

A/B 源码都已加入此功能并编译通过；本次只将新 B 镜像 219,084 B（CRC32 `0xEDA4009D`）通过 IAP 烧录到原确认 A 的非活动槽。`FW END TARGET=B ... ATTEMPTS=2 RESETTING` 后，B 自动健康确认：`CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=209`。A 的板上镜像仍是上一版，只含上电快照。

板上 IDLE 测试：`ANALOG LIVE VALID=1`，PC4 原始值约 569–587、PC5 约 1430–1451，`AGE_MS` 约 10–85；约 1.1 s 增加 11–12 组样本，`ERRORS=0`。同期 `SELFTEST READY=1 MASK=0x000`，ADC/FOC 计数各增加约 23,200–23,400，`STATUS MODE=IDLE FLT=0`。复查至累计 1086 组样本（约 109 s）仍为零错误。未发送 `START`，尚未验证电机活动时采样时序或保护动作。

复查命令：

    powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\selftest_status_smoke.ps1 -Port COM5 -ExpectedSlot B
    powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\analog_live_smoke.ps1 -Port COM5 -ExpectedSlot B

### 工厂 VREFINT 电压换算：A 槽已烧录并验证

STM32G474 的本地 ST HAL 定义明确 `ADC_VREFINT_INSTANCE` 不包括 ADC2，因此在 ADC1 注入电流采样启动前，用 ADC1 规则通道读取一次内部 `VREFINT`；采样时间 640.5 个 ADC 时钟周期，并用芯片工厂校准常数估算 `VDDA/VREF+`。运行中不再碰 ADC1 规则组。新命令 `ANALOG VOLT` 把最新 PC4/PC5 原始值换算为 `VBUS_EST_MV` 和 `VTEMP_MV`；母线分压系数仍取手册标称 25，输出 `PROTECT=0` 明确仅为诊断。若参考电压无效或数据超过 500 ms，`VALID=0`，不输出可信电压。`VTEMP_MV` 是传感器引脚电压，**不是摄氏温度**。

A/B 源码编译通过；A Flash 220,340 B / 224 KiB（96.06%）、RAM 64,888 B；B Flash 220,020 B / 224 KiB（95.92%）、RAM 64,872 B。本次只将 A 镜像 220,340 B、CRC32 `0xC049C2CB` 烧录到原确认 B 的非活动槽。`FW END TARGET=A ... ATTEMPTS=2 RESETTING` 后 A 自动确认：`CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=212`。板上 B 仍是上一版，没有 `ANALOG VOLT` 命令。

板上测试：`VREF_RAW=1515`、`VDDA_BOOT_MV=3285`；`ANALOG VOLT VALID=1 VBUS_EST_MV=11772 VTEMP_MV=1142 AGE_MS=30 DIV=25 PROTECT=0`。与先前约 12 V 母线、PC5 约 1.11 V 的万用表读数分别相差约 -1.9% 和 +2.9%；两次测量不是严格同时进行，故只作为单点合理性核对。`ANALOG LIVE` 约 1.1 s 增加 12 组样本，`ERRORS=0`；ADC/FOC 各增长 23,605，`SELFTEST READY=1`、`STATUS MODE=IDLE FLT=0`。未发送 `START`。

复查命令：

    powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\analog_voltage_smoke.ps1 -Port COM5 -ExpectedSlot A -ExpectedBusMv 12000
    powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\analog_live_smoke.ps1 -Port COM5 -ExpectedSlot A

下一步需在驱动板手册允许的另一组母线电压下，保持电机 IDLE，以万用表实测电源与 VBUS 引脚，并与 `ANALOG VOLT` 对比，完成第二点线性核查。再单独设计电机活动状态下不影响相电流采样的测量与故障去抖。温度需 NTC 参数或校准点后才可定义可信的摄氏度和过温阈值；在这些验证前不把诊断值接入关断逻辑。

### 历史接线安全步骤（已完成，非当前操作指令）

1. 保持电机不转，不发送 `START`；断电时拍清楚驱动板接口丝印及现有信号线两端，确认实际的 `VBUS`、`VTEMP`、模拟 `GND`。
2. 先不接 MCU ADC。上电后用万用表直流电压档，以驱动板的采样 `GND` 为参考，分别测 `VBUS`、`VTEMP`；记录同时测到的实际母线电压和环境温度。绝不要把 12/24 V 的 `VIN` 直接接 MCU ADC。
3. 提供准备接入的两个**实际 MCU 引脚**，并核对它们未用于 PWM、SPI、UART、SWD 或现有电流采样。核对 ADC 允许输入范围和地参考后，才接模拟信号。若实测电压异常或接地关系不明，停止接线。
4. 引脚及实测量程确认后，再单独实现低优先级 ADC 采样、原始值诊断命令、有效性/断线判断、阈值与去抖；先只读验证，再考虑让欠压/过压/过温进入预检和运行中锁存关断。不要直接用上述理论值定保护门限。

本步完成接线、A 槽上电快照验证、B 槽 IDLE 低频采样验证，以及新 A 槽的工厂 VREFINT 电压估算验证；**未实现电机运行时的电压/温度保护**。
