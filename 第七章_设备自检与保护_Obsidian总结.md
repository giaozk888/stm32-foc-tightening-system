---
title: 第七章｜设备自检、故障保护与模拟采样诊断
aliases:
  - Stage 7 总结
  - STM32G474 第七章
tags:
  - STM32G474
  - PD6010B
  - FreeRTOS
  - FOC
  - ADC
  - 故障保护
  - 实验记录
date: 2026-09-25
status: 已完成软件诊断与部分板上验证；模拟量根因及运行保护待验证
---

# 第七章｜设备自检、故障保护与模拟采样诊断

> [!important] 本章结论
> 已建立 `START` 前自检、ADC/FOC 计数停滞锁存、过流快照接口、单向 `ANALOG SAFE` 停桥状态，以及 PC4/PC5 只读电压诊断。**没有完成可投产的母线过压/欠压或过温保护**；模拟采样仍有孤立尖峰，三取中值也偶尔失效。当前暂停模拟链排查，不进行升压或电机动作实验。下文的“当前状态”覆盖各分节笔记里写于当时的历史状态。

## 1. 项目边界与信号链

本章对象是 NUCLEO-G474RE（STM32G474RET6）＋ GenBotter PD6010B＋有感 FOC 电机。PWM/电流环与本章低频模拟诊断是**两条不同的采样链**：

```text
TIM1 TRGO2 20 kHz ──> ADC1 注入组 IU、ADC2 注入组 IV
                    └─> 电流滤波 / W 相重建 / FOC / 2 A 软件跳闸

PD6010B VBUS ──> PC4 / ADC2_IN5 ┐
PD6010B VTEMP ─> PC5 / ADC2_IN11 ├─> IDLE 约 10 Hz 规则组只读诊断
             信号地 ──> AGND       ┘

PC6 ──> CTRL_SD：驱动使能/关断
```

手册标称 `VBUS = POWER / 25`，但 `POWER` 是驱动板内部防反接后的母线，未必严格等于外部电源端电压。`VTEMP_MV` 是 PC5 引脚电压，不是摄氏度；没有 NTC 参数/校准，不设温度保护阈值。`FOC_DC_BUS_V=12.0f` 是控制算法固定参数，也不是 ADC 实测母线。PC4/PC5 的 ADC2 映射由 CubeMX 和本地源码核对；实测约 `PC4=0.48 V`、`PC5=1.11 V`（12 V 条件）。详见 [[STAGE7_3_POWER_SENSING_WIRING_AUDIT]]。

## 2. 按阶段完成的步骤

| 阶段 | 实施内容 | 已验证范围 / 仍缺什么 |
| --- | --- | --- |
| 7.1 | `SELFTEST STATUS` 汇总 ADC、FOC、编码器、零点、UART、模式、转速、IAP/trial 和计数新鲜度；ProtocolTask 与 TighteningTask 对 `START` 双重预检 | A/B 编译、IAP 自动确认；正常态 `READY=1 MASK=0x000`。未逐一故障注入验证拒绝分支。[[STAGE7_1_PREFLIGHT_SELFTEST]] |
| 7.2 | 在 1 kHz MotorControlTask 中发现 ADC/FOC 计数超过 50 ms 停滞后，锁存故障并拉低 CTRL_SD；原因码 5/6 | 正常运行不误触发；未人为停 ADC/FOC 检验实际动作时延。[[STAGE7_2_ADC_FOC_CHAIN_WATCHDOG]] |
| 7.3 | 接 VBUS→PC4、VTEMP→PC5；上电快照 `ANALOG BOOT`；IDLE 低频 `ANALOG LIVE`；启动时 ADC1 VREFINT 估算 VDDA，并显示 `ANALOG VOLT` | 12 V 单点与万用表大致一致；规则组不调用会停止注入 IV 采样的 `HAL_ADC_Stop()`；`PROTECT=0`。[[STAGE7_3_POWER_SENSING_WIRING_AUDIT]] |
| 7.4 | 共用 12 V 电源不调压，做 30 s IDLE 基线及 ADC/FOC 计数检查 | 一次 30 s 采样有效并不代表没有偶发尖峰。[[STAGE7_4_ANALOG_FIXED_SUPPLY_STABILITY]] |
| 7.5 | 首次过流时保存 RAM 快照，`FAULT SNAPSHOT` 可查询原始/滤后 U、V，重建 W、电流、时间和最近模拟量 | 接口在后续版本上板，正常无故障时 `VALID=0`；**过流捕获路径未主动实测**。[[STAGE7_5_OVERCURRENT_FAULT_SNAPSHOT]] |
| 7.6 | 增加单向 `ANALOG SAFE`：已确认且静止时先关驱动、再停 PWM/MOE，普通 START 不可退出；复位才解除 | MCU 回读 `SD=0 MOE=0 FOC=0`，停桥后 ADC2 低频采样仍更新；驱动板 CTRL_SD 曾由万用表实测 0 V，但**每次复位后都要重新核对**。[[STAGE7_6_ANALOG_SAFE_DIAGNOSTIC_MODE]] |
| 7.7 | 审计 60-count 阶跃拒绝、3 点中值、20 次连续拒绝及重建 W；把滤波上下文加入 `FAULT FILTER` | 离线数值推演和无跳闸接口烟测通过；未复现旧 `R=1` 根因。[[STAGE7_7_CURRENT_FILTER_TRIP_AUDIT]] |
| 7.8 | 12/13/14 V 只读安全态烟测；发现真实供电稳定时 `ANALOG VOLT` 偶发高估；换杜邦线后仍复现 | 在停 PWM、MOE=0 时也可出现尖峰，不能只归咎 PWM 或那一根杜邦线；升压实验已停止并回到 12 V。[[STAGE7_8_ANALOG_SAFE_HARDWARE_SMOKE]] |
| 7.9 | PC4 同通道双采样 `ANALOG PAIR` | 第一次、第二次都曾独立尖峰，不能简单丢弃首读。[[STAGE7_9_ANALOG_PC4_PAIRED_SAMPLE]] |
| 7.10 | SAFE 态 PC4 三采样和只读中值 `ANALOG TRIPLE` | 初次 120 s 中值压住孤立尖峰；曾因协议 `msg[192]` 截断回复，压缩输出后修复。[[STAGE7_10_ANALOG_PC4_TRIPLE_MEDIAN]] |
| 7.11 | 同一 ADC2 上加 PC5 三采样对照 `ANALOG PC5 TRIPLE` | B 槽 120 s 内 PC4、PC5 各新增 44 组 >60-count 差异；并非 PC4 独有。[[STAGE7_11_ANALOG_PC5_CONTROL]] |
| 7.12 | A 槽将 PC4/PC5 采样时间从 47.5 增到 247.5 ADC cycles，保留 B 作为基线 | PC4 异常组 44/1216→28/1217，PC5 44/1215→43/1216；两路尖峰均未消失，不能仅凭单轮比较断言改善。[[STAGE7_12_ANALOG_SAMPLE_TIME_AB]] |

## 3. 关键问题、排查与解决办法

### 3.1 `IDLE` 不等于功率级断电

旧日志显示 `MODE=IDLE` 时仍可能 `EN=1`、FOC 电流环运行、CTRL_SD 为 HIGH。因此变压或诊断不能只看 IDLE。解决：引入 `ANALOG SAFE` 单向停桥，检查软件 `SD/MOE/FOC` 均为 0，并曾在驱动板实测 CTRL_SD 为 0 V。**SAFE 不是跨复位的硬件急停**：升级、断电或复位后启动流程可能重新使能桥臂。

### 3.2 14 V 条件曾出现 `R=1`

`R=1` 对应现有三相软件 2 A 电流跳闸，不是 VBUS 过压，因为模拟量仍是 `PROTECT=0`。缺少当时的瞬时原始/滤后电流，不能判断是真电流、重建 W 电流、采样时序、线束还是噪声。解决的是**可观测性**：增加 `FAULT SNAPSHOT` 与 `FAULT FILTER`，故障后、复位前读取；没有再次主动制造过流，根因仍未定。不通过提高 2 A 阈值掩盖问题。

### 3.3 模拟电压估算的偶发尖峰

12 V 时曾短时估算到约 30.8 V；14 V 停桥测试也遇到约 15.4 V 的估算，换线后 12 V 仍偶发约 13.3 V。`ERRORS=0` 只说明 HAL 转换完成，不说明读数代表真实稳定电压。PC4/PC5 双通道均出现单点尖峰，长采样时间也未根治。万用表只能核对较慢的电压，不能排除微秒级扰动；现有 8 路数字逻辑分析仪不能直接测模拟幅值。**当前不启用过压/欠压和过温保护。**

### 3.4 中值也不能直接当保护值

Stage 7.10 的两分钟实验里三取中值有效压低孤立峰值，但 Stage 7.12 出现 PC4 三元组 `752,576,778`，中值 `752`，按标称换算约 15.1 V，而电源仍约 12 V。说明两笔同时异常时中值也会偏高。解决：保留原始样本、极差计数和只读诊断；**不把中值接入安全关断**，先查根因，再制定量程、时效、去抖和失效策略。

### 3.5 工具与协议中的几个小坑

- Windows PowerShell 5.1 不支持 `[Convert]::ToHexString`；旧传输脚本曾在 `FW BEGIN` 后失败并执行 `FW ABORT`。改用 `[BitConverter]::ToString(...).Replace('-', '')` 后可兼容 PowerShell 5.1/7。
- `ANALOG TRIPLE` 初版回复超过 `Protocol_HandleLine()` 的 `msg[192]`，尾部被截断。压缩字段输出，保留关键信息并保持回复小于缓冲区；命令可解析不等于整行回复未被截断。
- IAP 复位后的首次 COM5 请求偶尔超时或显示 `PENDING` trial，不能立即判升级失败；等健康窗口后只读复查 `CURRENT=CONFIRMED`、`PENDING=-`、`ATTEMPTS=0`。反复异常则停下调查，不手动强制 confirm。

## 4. 当前板上状态与内存

最后一次只读复核（2026-09-25）：`CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=230`，`MODE=IDLE FLT=0`，软件 SAFE 锁存 `SD=0 MOE=0 FOC=0`，约 12 V，`ANALOG VOLT PROTECT=0`。A 是 **247.5-cycle 对照版**，已构建、IAP、trial、自动确认；B 保留 **47.5-cycle 基线版**，但当前 metadata 的 confirmed slot 是 A。没有在 A 最近这次复位后重新用万用表测 CTRL_SD；不以此前的实测替代当前物理确认。

| 当前镜像 | Flash | 224 KiB 槽余量 | RAM | 备注 |
| --- | ---: | ---: | ---: | --- |
| A | 225,116 B | 4,260 B | 65,080 B | 当前运行，CRC32 `0xF3F00847` |
| B | 224,748 B | 4,628 B | 65,064 B | 已验证的基线，CRC32 `0xE403A41C` |

Flash 余量只有约 4–5 KiB。后续模块不应继续无节制地堆到 APP；先精简临时诊断、评估栈/静态 RAM、保留 A/B 和 bootloader 空间。**本章未修改** Flash 布局、DBANK/BFB2、A/B 地址、Metadata V3 布局或 SRAM mailbox。

## 5. 常用只读命令（留档；现在不用执行）

串口 Protocol V2，每行以请求 ID 开头：

```text
2000 FW STATUS
2001 STATUS
2002 SELFTEST STATUS
2003 ANALOG SAFE STATUS
2004 ANALOG LIVE
2005 ANALOG VOLT
2006 ANALOG TRIPLE
2007 ANALOG PC5 TRIPLE
2008 FAULT SNAPSHOT
2009 FAULT FILTER
```

若以后在**原有 12 V 接线、已确认 A、SAFE 已锁存且未复位**的条件下做纯只读复核，从工程根目录运行：

```powershell
Set-Location 'D:\new project'
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\analog_safe_smoke.ps1 -Port COM5 -ExpectedSlot A -ExpectedBusMv 12000 -VerifyOnly
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\analog_pc4_pc5_compare.ps1 -Port COM5 -ExpectedSlot A -Seconds 120 -PollMs 5000
```

不要把上述脚本用于改线/接地后的原始电路之外：`analog_safe_smoke.ps1` 会要求 PC4 换算母线接近 12 V，接地后必然不满足。`ANALOG SAFE` 本身会改变桥臂状态；本节列出的脚本在 `-VerifyOnly` 时不进入/退出 SAFE。任何复位之后都要重新验证状态；不要在调高电压时复位。

## 6. 这章最重要的知识点

1. **自检是“已检查项目的健康”，不是安全认证。** `READY=1` 只覆盖现有软件条件，不能代表欠压/过温/急停已实现。
2. **任务看门狗不是独立硬件看门狗。** 1 kHz 任务本身若不被调度，无法保证抓到 ADC/FOC 停滞。
3. **ADC 规则组与注入组共享 ADC2 资源。** 运行中随意 `HAL_ADC_Stop()` 可能停掉相电流注入采样；PC4/PC5 采样时间须在注入转换启动前配置。
4. **数据年龄、原始值、换算值要分开看。** VREFINT 启动估算只修正参考电压，不能消除随机尖峰；`VTEMP_MV` 不是温度。
5. **故障快照要在关断后、复位前保存和读取。** RAM 快照随复位丢失；触发帧与最近低频 VBUS 值也不能误认为同步测量。
6. **观察到相关性不等于根因。** 停 PWM 后仍有尖峰，说明不能单独归咎 PWM；两路都有尖峰，也不能直接宣布 STM32 ADC 损坏。
7. **试验固件需保留回退。** 本次 A/B 的采样时间差异是有意的对照，不要在未定结论前把 A 同步到 B。

## 7. 暂停点与后续独立工作

- 暂停：PC4/PC5 尖峰根因、低阻抗输入隔离、真实过流故障注入、运行中母线/温度保护、14 V 电机测试。恢复前另开安全评估，先确认线束、电源、物理 CTRL_SD 与回退方案。
- 可独立推进：对截图所列“SPI 编码器＋中心对齐互补死区 PWM”做**只读代码/配置审计**，先形成已实现、待验证及风险清单，不烧录、不启动电机。随后才能选不依赖模拟电压链的下一项实现。
- 截图是目标能力清单，不是本项目已通过的测试报告；尤其不能把“95% 占空比”“500 次升级零失败”等文字写成本板已完成的成绩。

## 相关分节

[[STAGE7_1_PREFLIGHT_SELFTEST]] · [[STAGE7_2_ADC_FOC_CHAIN_WATCHDOG]] · [[STAGE7_3_POWER_SENSING_WIRING_AUDIT]] · [[STAGE7_4_ANALOG_FIXED_SUPPLY_STABILITY]] · [[STAGE7_5_OVERCURRENT_FAULT_SNAPSHOT]] · [[STAGE7_6_ANALOG_SAFE_DIAGNOSTIC_MODE]] · [[STAGE7_7_CURRENT_FILTER_TRIP_AUDIT]] · [[STAGE7_8_ANALOG_SAFE_HARDWARE_SMOKE]] · [[STAGE7_9_ANALOG_PC4_PAIRED_SAMPLE]] · [[STAGE7_10_ANALOG_PC4_TRIPLE_MEDIAN]] · [[STAGE7_11_ANALOG_PC5_CONTROL]] · [[STAGE7_12_ANALOG_SAMPLE_TIME_AB]]
