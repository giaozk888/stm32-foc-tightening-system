---
date: 2026-10-06
status: 初始离线记录；后续B基础上板通过；不是完整硬实时验收
---

# AS5047P SPI DMA改造离线记录

实现和白话说明：[[嵌入式实习面试笔记/17_SPI_DMA定时采样_白话实现与验证]]。

`AS5047P_SPI_DMA`默认OFF；独立`EncoderDmaReadOnly`继承原RouterRpcReadOnly并启用新驱动。最初离线阶段没有串口/SSH/SWD操作、刷写、复位或运动指令，没有改Bootloader、Flash分区、ESP32、热点或云端配置。后续上板结果单独记录在本文末尾及[[嵌入式实习面试笔记/18_SPI_DMA实机验收_20261006]]。

## 构建结果

| 槽 | BIN/FLASH占用 | RAM链接占用 | SRAM中的驱动对象地址 |
| --- | --- | --- | --- |
| A | 190300 B | 88960 B | 0x20003070 |
| B | 189396 B | 88936 B | 0x2000305C |

每槽FLASH预算229376 B，RAM链接区域131008 B。这里的RAM数包含链接器预留，不是运行时堆/栈余量。DMA字位于静态engine对象内部，属于保守允许的DMA可访问SRAM；没有放在任务栈。

新镜像文件与SHA256：

- `foc2_app_a/build/EncoderDmaReadOnly/foc2.bin`：`A7092048B8BF1D62C07773201EC0B8DF7D0069CB177538A3E43A7A7845A7B144`
- `foc2_app_b/build/EncoderDmaReadOnly/foc2.bin`：`E48B31D72CDE4BA9B9B0C9BE3BE17A9CF045085D98DF45F23224A1BDEAC4211C`

未覆盖既有`build/RouterRpcReadOnly`镜像（A 188892 B、B 187996 B）。目标构建仍有main.c既有未使用变量/函数警告；新DMA配置让旧TransferAdapter成为未使用函数，也有一条对应警告。新独立驱动没有新增编译警告。本轮不宣称零警告。

## 已执行

- `tools/test_as5047p_dma.ps1`：CTest 6/6；DMA状态机各槽19场景332检查通过；关闭新开关保留旧main/通信源；A/B新分支一致。
- `tools/build_encoder_dma.ps1`与最终main增量重编译：A/B成功。
- `tools/test_router_network.ps1`：Router CTest 2/2、Pigweed RPC CTest 2/2、Python 26/26通过。
- `ctest --test-dir tests/uart_zero_copy_host/build --output-on-failure`：现有UART/日志/所有权测试8/8通过。
- ELF `nm`：DMA1_Channel4/5与TIM2 IRQ为新驱动强符号；新ELF中没有旧AS5047P_Transfer16/TransferAdapter链接符号。
- `.su`：RX/TX IRQ自身栈帧0 B，TIM2 IRQ自身16 B；不代表包括调用链/异常/嵌套/FPU的总栈预算。

## 最初离线阶段未执行（后续部分已补齐）

当时实际DMA寄存器行为、DMA与ADC竞争、CS波形、EF恢复实机序列、负载下最坏耗时、关断延迟、实际dt/电角度预测质量、MISO断线/磁场异常检测、升级/Flash写入与周期采样互斥、运行时栈余量均未上板验收。后续已补正常DMA执行、20 kHz ADC背景共存、SAFE单读/超时恢复及MotorControlTask已观测栈余量，详见末节；其余不能自动视为通过。

200 μs是绝对时间软件预算。TIM2可以在该时间产生比较事件，但高优先级中断、PRIMASK和Flash停顿仍会延后软件关断。不能把状态机模拟成功、ELF编译成功或旧驱动的测量报告当作严格硬实时证明。后续实机验收需重新确认隔离与刷写/复位授权。

## 后续上板预检：尚未刷写

用户要求上板后，先进行只读检查并请求当次隔离/刷写/复位确认。COM5存在但PING无回复；SWD Hot Plug已恢复可用，完整Flash备份和核对证明板上仍是旧A、GEN=299。旧固件故障码7，电流零点校准失败，UART运行门控和RX DMA尚未开启；不是新版DMA失败。需要现场确认采样/驱动板供电与接线以及当次授权，未绕过校准、未复位、未写入新版。详细预检记录：`safety_backups/20261006-encoder-dma-live/PREFLIGHT.md`。

## 获当次授权后的实机结果

用户确认隔离、供电稳定并允许刷写/复位后，复位旧A，零点校准及串口恢复正常，重新SAFE锁定；IAP写入非活动B，125.12秒上传，CRC `A1A93960`，5秒连续健康通过，最终B确认、GEN=302。旧A、Bootloader、KVS/保留区和参数页全量回读不变。没有发送运动指令，没有绕过校准或调整保护阈值。

- 新B启动编码器20/20；正常运行与20 kHz ADC/电流环共存，后续累计READS=24518，FAIL/TIMEOUT/IO/SCHED/STALE均0，软件MAX_US=35。
- SAFE下1000次单次DMA读取全部HAL=0；这一组与上述较长周期运行分别归档，不混作同一批计数。
- SAFE下临时屏蔽DMA RX IRQ14，一次读取HAL=1、ST=2，TIMEOUT/FAIL各加1、MAX_US=200；仅恢复同一IRQ后下一笔HAL=0、ST=0。
- 最终SAFE=1、SD/MOE/FOC=0、FLT=0；CS高、DMA4/5关闭、SPI DMA请求/TIM2比较关闭、IRQ14恢复、CFSR=0，寄存器核对通过。
- 最终FAIL=1、TIMEOUT=1、MAX_US=200是故意注入历史，未清零，不应误报为正常采样失败。
- 确认等待期的TIGHTEN FAULT事件也见于10月5日旧固件日志；当时未采故障码，本轮不将其归因为新DMA。详见新验收笔记的限制说明。

原始证据：`safety_backups/20261006-encoder-dma-live/`。新波形、极限负载/WCET、EF六帧、物理断线/磁场异常、实际带功率关断延迟和Flash运行期互斥仍未验收。**本轮结论是基础功能和SAFE超时/恢复通过，不是严格硬实时全面通过。**
