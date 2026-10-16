---
title: Stage 8.3 - AS5047P 1 kHz 时序与任务栈离线审计
tags:
  - STM32G474
  - AS5047P
  - SPI
  - FreeRTOS
date: 2026-09-25
status: b-slot-idle-runtime-verified-safe-latched
---

# Stage 8.3：AS5047P 1 kHz 时序与任务栈离线审计

## 范围和结论

先审计本地 A/B 固件源码、GCC `*.su` 栈报告和 Stage 8.2 的假 SPI 测试；随后按需求给两槽加入只读诊断计数与安全锁存状态下的单次读取命令。**尚未烧录、复位或操作电机**。两槽固件构建和四项主机测试通过；这仍不证明 1 kHz 实时性或运行时栈安全。

发现三个尚未关闭的风险：

1. 正常角度读取消耗 2 个 16-bit SPI 帧；EF 错误恢复最多 6 帧。每帧 `HAL_SPI_TransmitReceive(..., Timeout=10U)`，异常情况下整次角度读取有约 6 × 10 ms 的**超时预算量级**，远大于 1 ms 任务周期。这不是严格的墙钟上界：HAL tick 分辨率、抢占、HAL 收尾等待和中断状态都会影响实际耗时。
2. `MotorControlTask` 每 1 tick 运行一次，但无论发生多少延迟，总向 `FOC_EncoderSpeedUpdate()` 传入固定 `0.001f`。如果丢周期，速度估算的时间基准会偏小。该问题不能靠编译或假 SPI 测试排除。
3. `MotorControlTask` 栈配置 768 个 32-bit 栈单位，即 3072 B；工程 `configCHECK_FOR_STACK_OVERFLOW=0`。本次已增加低优先级任务的高水位采样，但**目标板还没返回测量值**。编译器栈帧数字不能代替真实余量。

## 源码证据与计算

| 项目 | 当前代码 | 解释 |
| --- | --- | --- |
| 调度 | `configTICK_RATE_HZ=1000`；`MotorControlTask` 优先级 4，循环尾 `vTaskDelayUntil(..., 1 tick)` | 名义周期 1 ms，不保证每次执行耗时 <1 ms |
| 采样调用 | `MotorControlTask` 中无故障时调用 `FOC_EncoderSpeedUpdate(0.001f)` | 时间参数固定；调度超时不会自动补偿 |
| SPI | SPI1，16-bit，CPOL=0、CPHA=2EDGE，预分频 32 | HSI 16 MHz /4 ×85 /2 = 170 MHz；APB2 /1，故理论 SPI SCK ≈5.3125 MHz；单帧 16 bit 线时约 3.01 µs |
| CS 守护 | 每帧 CS 下降后、上升前、上升后各有 128 次 `NOP` 循环 | 单次 128 NOP 指令的理论下限约 0.75 µs，实际还包含循环、HAL 和 GPIO 开销；**不是实测时序** |
| 事务 | `ReadAngleVia`：角度 2 帧；EF 时 ERRFL 2 帧 + 再读角度 2 帧 | 主机假设备分别验证了 2 帧和 6 帧路径、失败路径不输出新角度 |
| 阻塞 | 每个 `AS5047P_Transfer16` 调一次阻塞式 `HAL_SPI_TransmitReceive(..., 10U)` | 10 ms 是单帧 HAL timeout，不是整次读角度 timeout；异常路径可严重超 1 ms |
| 故障行为 | 读角度失败使 `encoder_valid=0`、`foc_fault=1`；MotorControlTask 随后关闭功率级 | 故障最终进入安全状态，但阻塞期间仍可能损失多个控制周期 |
| 模拟量安全锁存 | `analog_safe_latched != 0` 时 MotorControlTask 直接关闭功率级并跳过编码器读取 | 当前 SAFE 状态下的任务日志不能证明 AS5047P 运行时延迟 |

仅看 SPI 线上的 16-bit 时钟，正常两帧约 6.02 µs，EF 六帧约 18.07 µs；这些是**理想线时**，不能据此声称整个 HAL 事务满足 1 ms。最坏超时、线程抢占与 CS 守护都需在目标板测量。

`main()` 中还有位于 `vTaskStartScheduler()` 后面的旧编码器更新循环。正常调度器不会返回，故该循环通常不运行，不能把它算成与 MotorControlTask 并发访问 SPI 的证据；若调度器异常返回，系统已属另一种故障路径。

## 静态栈报告

GCC `-fstack-usage` 的 A 槽当前报告：`MotorControlTask` 40 B、`FOC_EncoderSpeedUpdate` 120 B、`AS5047P_ReadAngle` 280 B、`AS5047P_ReadAngleVia` 88 B、`AS5047P_ReadRegisterVia` 64 B、`AS5047P_TransferAdapter` 24 B、`AS5047P_Transfer16` 32 B、`HAL_SPI_TransmitReceive` 48 B。这些只是各函数的静态栈帧估计；调用链中还包括 GPIO/HAL/FreeRTOS、可能的 FPU 上下文和中断栈，且优化可能改变内联与帧复用，因此**不据此宣布 3072 B 足够**。A/B 均应在板上读取 MotorCtrl 的最小剩余栈高水位后再定结论。

## 已加入的板上诊断（尚未烧录）

A/B `main.c` 均在系统时钟初始化后开启 DWT 周期计数器，并检查计数确实前进。每次 `AS5047P_ReadAngleVia()` 调用前后取 `CYCCNT` 差值，累计 `READS`、`FAIL`、`OVER1MS`，并保存 `LAST_US`、`MAX_US`。这是包含中断/抢占影响的**整次 SPI 事务耗时**，不包含读角度之后的转速 PI 计算。低优先级 `MonitorTask` 每秒读取一次 MotorCtrl 任务栈高水位，避免在 1 kHz 控制循环里扫描 3 KiB 栈。两个诊断命令加入 `HELP`：

```text
2000 ENC DIAG
2001 ENC SAMPLE
```

`ENC DIAG` 返回两行：累计事务计数和 MotorCtrl 最小剩余栈字节数。`STACK VALID=0` 表示监控任务尚未取到高水位；`DWT=0` 表示计数器未开启，不能解释时间值。`SAFE_NOW=1` 只表示查询时处于安全锁存，不代表高水位覆盖过完整 FOC 路径。

`ENC SAMPLE` 仅当 `analog_safe_latched=1` 且 SD=0、MOE=0、FOC=0 时允许执行，手动读取**一次**真实 AS5047P，并返回 `HAL` 状态、`RAW` 和耗时 `US`。命令绝不使能功率级；正常模式请求会返回 `ANALOG_SAFE_REQUIRED`。在 SAFE 下 MotorCtrl 会跳过常规编码器采样，所以这个手动命令只能验证真实 SPI 单次耗时，**不能证明运行中的 1 kHz 任务已达标**。SPI 断线时仍可能按原 HAL 超时阻塞该协议任务。

最新离线构建：A `FLASH=226856 B`、`RAM=65120 B`；B `FLASH=226488 B`、`RAM=65104 B`，均未超出 224 KiB 槽。编译器仍报原有 unused 警告，没有新增编译错误。

## 下次上板的安全验证门槛

1. 先确认两槽可回退，检查 PD6010B 的 `CTRL_SD=0 V`、MOE=0、FOC=0；目前 Stage 7 模拟量尖峰仍未排清，不启动电机。
2. 在确认软件/硬件安全条件后，才考虑把新镜像试运行于可回退槽。先用 `ENC DIAG` 读取 `DWT` 和 `STACK VALID`，再在 SAFE 状态下用 `ENC SAMPLE` 取真实 SPI 单次耗时；逻辑分析仪仍可独立核对 CS/SCK。不能只靠 1 ms HAL tick 测微秒级时序。
3. 高水位由低优先级 MonitorTask 调用 `uxTaskGetStackHighWaterMark(motor_control_task_handle)` 每秒获取；返回栈单位乘 `sizeof(StackType_t)=4` 成为 `FREE_B`。SAFE 状态下的余量不覆盖完整 FOC 路径，不能据此决定运行时栈足够。
4. 根据实测，再决定是否把编码器读取改为非阻塞/有严格事务级超时、是否将调速 `dt` 改为真实间隔。此类控制逻辑修改需单独评审并先做无功率级测试。

## 复现命令

```powershell
ctest --test-dir .\tests\as5047p_host\out --output-on-failure
cmake --build .\foc2_app_a\build\Debug -j 4
cmake --build .\foc2_app_b\build\Debug -j 4
rg -n "AS5047P_ReadAngle|FOC_EncoderSpeedUpdate|MotorControlTask|HAL_SPI_TransmitReceive" .\foc2_app_a\build\Debug\CMakeFiles\foc2.dir\Core\Src\main.c.su
```

本步结果：`ctest` 4/4 通过；A/B 加入诊断后重新构建成功。后续 B 槽 IDLE 实测见下；**尚无带电机负载的运动结果**。

## 首次 B 槽试运行记录

在用户确认 PD6010B 输入端实测 0 V、U/V/W 已断开后，由已确认的 A 槽把诊断版 B 镜像写入非活动槽。`FW END` 返回 `TARGET=B SIZE=226488 CRC32=0x14E28827 ATTEMPTS=2 RESETTING`。复位后 COM5 无响应；SWD hot-plug 只读检查 PC=`0x08058772`，对应 B 镜像的 `Error_Handler` 循环。SRAM 中静态电流零点 `iu_zero_raw=0`、`iv_zero_raw=0`；代码 `ADC_CurrentZeroCalibrate()` 要求二者均在 `1000..2200`，断电的 PD6010B 无法提供有效电流采样中点。`encoder_diag_reads=0`，表示故障发生在编码器启动检查和新诊断命令可用之前。

因此“驱动板始终断电即可验证新编码器诊断”的先前计划不成立。当前 B 已进入错误死循环；**不要在驱动板仍为 0 V 时反复复位**，否则试运行次数可能被耗尽并回滚。后续仅在 U/V/W 分别断开且绝缘、继电器触点无负载、确认板端 12 V 与 CTRL_SD=0 V 后，才可考虑再次复位让 B 走完启动；复位会解除软件 SAFE，驱动板输出端即使没有电机也可能带电，切勿触碰。此记录不是成功的时序/栈测试。

## 恢复 12 V 后的 B 槽验证

用户确认 PD6010B 输入约 12 V、CTRL_SD 约 0 V、U/V/W 仍分别断开绝缘且继电器触点无外部负载后，执行了一次 SWD 软件复位，同时被动监听 COM5。B 槽启动日志：静态零点 U=1560/V=1562，编码器启动检查 `OK=20/20`，双 ADC 和 20 kHz FOC 链正常；BootHealth 在 5 秒持续健康后请求确认并再次复位。随后 `FW STATUS`：`CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 GEN=234`。立即发送 `ANALOG SAFE` 并复查 `LATCHED=1 SD=0 MOE=0 FOC=0`。这次不再是 trial，也没有再擦写 A 槽。

安全锁存后的诊断结果：

```text
ENC DIAG  DWT=1 READS=18890 FAIL=0 OVER1MS=0 LAST_US=135 MAX_US=141 SAFE=1
ENC STACK VALID=1 FREE_B=2168 SAMPLES=18 SAFE_NOW=1
ENC SAMPLE HAL=0 RAW=3984 US=69 SAFE=1 SD=0 MOE=0 FOC=0
ENC SAMPLE HAL=0 RAW=3980 US=69 SAFE=1 SD=0 MOE=0 FOC=0
ENC SAMPLE HAL=0 RAW=3982 US=69 SAFE=1 SD=0 MOE=0 FOC=0
ENC DIAG  DWT=1 READS=18893 FAIL=0 OVER1MS=0 LAST_US=69 MAX_US=141 SAFE=1
ENC STACK VALID=1 FREE_B=2168 SAMPLES=34 SAFE_NOW=1
```

解释：B 槽 IDLE、无电机连接的这段约 18.9k 次读取中，没有观察到 SPI 失败或超过 1 ms 的整次角度事务；最大 141 µs，安全锁存后单次约 69 µs。MotorCtrl 768 words（3072 B）配置中最少剩余 2168 B，约使用 904 B。这是 FreeRTOS 高水位观察值，不是理论最坏情况，也不覆盖运动、EF 恢复、SPI 断线和不同中断负载。Stage 7 模拟量尖峰仍未解决，**不能据此开始带电机的完整 FOC 试验**。板子当前已在软件 ANALOG SAFE；如断电重启，SAFE 会解除，须重新核对。

相关：[[STAGE8_1_AS5047P_HOST_TESTS]]、[[STAGE8_2_AS5047P_FAKE_SPI]]、[[第七章_设备自检与保护_Obsidian总结]]。
