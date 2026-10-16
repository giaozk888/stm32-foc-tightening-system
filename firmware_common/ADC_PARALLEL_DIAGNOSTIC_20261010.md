# 三 ADC 并行原码诊断

## 这次改了什么

原来的三路版由 ADC1 先采 U、再采 W，ADC2 同时采 V。本版让 W 使用独立 ADC5，不再等待 U 的第二个转换位置。

| 信号 | 引脚 | ADC | DMA |
| --- | --- | --- | --- |
| IU | PA0 | ADC1 IN1 | DMA1 CH3 |
| IV | PA1 | ADC2 IN2 | DMA1 CH4 |
| IW | PA8 | ADC5 IN1 | DMA2 CH1 |

三路均为规则单通道、12 bit、12.5 周期采样，触发源均为 TIM1 TRGO2 上升沿。ADC12 与 ADC345 都用 SYSCLK 异步路径 /4（系统时钟 170 MHz，ADC 时钟 42.5 MHz）。定时器配置不变，名义触发频率 20 kHz。

“并行”在这里表示三个独立 ADC 接收同一事件，不是芯片的三 ADC multimode，也不宣称跨 ADC 时钟组采样孔径偏差严格为零。未经外部同步模拟信号或仪器测量，不能标记为零时间偏差已验收。

## 数据如何保证完整

每路各有 4096 个 uint16_t 静态槽位，三路共 24 KiB。使用有限长度 NORMAL DMA，不循环覆盖。三个 ADC 和三个 DMA 全部 arm、检查成功后，才开启定时器；所有功率输出始终关闭。

流程：初始化 ADC5/PA8、校准 → 保存 ADC1/2 原配置 → 停注入采样 → 配置三个单通道规则组 → arm 三路 DMA → 开内部触发 → 三路完成 → 停触发 → 前台停止 DMA/恢复 ADC1/2 → 检查计数及错误 → 计算 CRC、允许读取。

READY 要求三路各 4096 点、各 1 次完成回调、无 ADC/DMA 错误、恢复成功、输出仍锁定。第三路漏采、重复完成、中途失去锁定、超时或恢复失败，都不能导出为有效采集。每次启动最多执行一次 SAMPLE，失败不自动重试。

CSV/CRC 使用逻辑 U,V,W 顺序，逐点小端字节计算 CRC32；异常原码保留，不滤掉尖峰、不提高电流保护阈值、不发布零点，不据此使电机就绪。

## 如何启用与使用

新增 `ADC_DMA_PARALLEL_DIAGNOSTIC=ON`，默认关闭，必须同时启用 `ADC_DMA_THREE_PHASE_DIAGNOSTIC`、`ADC_DMA_RAW_DIAGNOSTIC`、`ZERO_RETEST_BOOT`。原两路和顺序三路驱动仍保留，不修改普通 FOC 的双 ADC 电流反馈或 W 重建。

本地 UART 命令：`ADC PAR STATUS`、`ADC PAR SAMPLE`、`ADC PAR READ <index>`。READ 每次返回 8 组原码，index 必须是 8 的倍数。旧 ADC DMA/ADC 3PH 命令不兼容，避免上位机把采样方式识别错。

SAMPLE 只在非试运行、非升级、无故障、输出锁定、ADC 时钟正确、ADC5 已校准且板端母线估值 10–14 V 时接受。实际供电与动力线隔离仍需现场确认，软件 ADC 估值不能替代现场电源限流。

## 验证范围

- A/B 编译成功，固件约 145 KiB，静态 RAM 约 108.7 KiB（包括既有 RTOS 堆和其他模块）；不是三路缓冲区独占这么多 RAM。
- 新驱动实际 C 代码在 HAL 模型下通过 49 个场景，覆盖六种完成顺序、部分初始化/恢复失败、ADC5 校准失败、第三路漏采、错误、超时和输出锁定。
- ADC 相关 39 项 Python 测试通过（其中包含旧驱动回归和 C 场景）；另零点与相电流保护各 5 项通过。
- 首次上板尝试只完成 Flash/输出寄存器只读检查，COM5 配置失败，没有开始擦写或采样。随后串口恢复，在未开始擦写的失败尝试后重新完成全部部署前置检查，官方 pw_transfer 升级成功。
- 实板已正常确认 A 槽，GEN=381，ADC5 初始化/校准完成，`W_READY=1`；两组时钟均 SYSCLK /4，PA8 模拟/无上下拉模式回读正确。完整 B 回退槽、bootloader、KVS 保留区和参数区前后字节相同。没有执行恢复性复位：串口在本次部署运行中正常回答，只有正常升级试运行/确认复位。
- 部署后独立只读检查再次通过，原码状态 IDLE，三路计数和 IRQ 均为 0，SD/MOE/CCER/CEN/FOC 均为 0。
- 用户开启 12 V 后尝试采集，但在发送 SAMPLE 前 ST-Link 和 COM5 从电脑设备列表消失。脚本记录 `No debug probe detected`、`sample_commands=0`，没有采到任何新原码，不能标记为三 ADC 实际采集通过。掉线原因未确定，也不能仅因掉线断言 MCU 或模拟电路故障。

成功部署证据：`safety_backups/adc-parallel-live-20261010/deployment-1791601987743125800.json`。只读复核：`capture-1791602262790553500.json`。采集前掉线记录：`capture-1791602331727685900.json`。

部署脚本只接受精确哈希的已知锁定固件，备份完整 Flash 到受限目录；通过已有官方 pw_transfer 写入非活动槽，校验整个回退槽、bootloader、KVS 和参数没有变化，再交给既有 bootloader 正常试运行、健康确认。没有强制确认、运动命令或直接写升级元数据。

主要文件：`adc_parallel_diag.c`、`adc_parallel_console.inc`、`tools/adc_parallel_acceptance.py`、`tools/adc_parallel_sample.py`、`tools/adc_parallel_report.py`。
