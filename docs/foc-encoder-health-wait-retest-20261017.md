# 自动确认复位等待修复：上板重验

## 结论

本次仅功率硬关闭的脚本等待及 ADC/FOC 计算验收通过；没有发送 START，没有启动电机或使能功率桥。脚本成功跨过应用正常健康确认复位，随后完成 31.85 秒观察。FOC 最大耗时 31.25 µs，50 µs deadline miss=0；实际 CCR 提交 late=0，观测最小 margin=15.05 µs。

这不是带电闭环、电流模拟精度、物理栅极波形或 WCET 证明；优先目标 <30 µs 仍未达到。本轮不再优化控制代码或重试。

## 条件、镜像与基线

用户明确授权本轮仅刷非活动 A 并必要复位，确认 12 V 关闭、U/V/W 动力线断开，仅测功率关闭计算。暂存通过后，用户回复开启驱动电源；试运行始终硬关闭 SD/MOE，IU→PA0、IV→PA1 不变。

- 镜像：`foc2_app_a/build/EncoderHealthReview/EncoderFocFirst/foc2.bin`，228964 字节。
- BIN SHA256：`c7eb539311b572e451589ec93b8c8eb4bdddcc4938e3c82c2f0911c45f434408`。
- ELF SHA256：`03407e5b186b9de756557b5fdcf2b955b9ca71cb0c56ed66e1f7f09443c9caea`。
- 本轮主机脚本基线由旧 B607 绑定到已验证的 B611 恢复收据 `encoder-health-restore-1792221718168887100.json`，完整 Flash SHA256 为 `1c0fc9f186e6222abaf94e0c3825b290ee29bf5055059b4d575fca623f9c942e`。没有跳过完整 Flash、回退 B 和槽外数据比较。
- 本轮固件 BIN/ELF 未修改，仅使用修复后的主机启动等待。执行前新增基线门禁和等待器共 23 项离线测试通过，镜像/布局/完整私有基线核对通过。
- 首次刷写命令被安全审查拒绝，未执行；用户补充明确授权后才执行下面的唯一一次暂存/试运行流程。没有换命令绕过拒绝。

## 自动确认复位等待

日志顺序：进入 A 试运行 → 5 秒连续健康检查 PASS → 请求 bootloader 确认并复位 → 新启动显示当前槽已确认，自动确认任务空闲。

`health_wait` 统计：

| 指标 | 实测 |
| --- | ---: |
| 启动等待总期限 | 60 s，未延长 |
| 实际等待时间 | 19.77497 s |
| 只读查询无 ACK 总数 | 24 |
| FW STATUS 无 ACK | 23 |
| MOTOR TEST STATUS 无 ACK | 1 |
| 重新核对后的 confirmed generation | 614 |
| 正常确认 | true |
| 后续观察时间 | 31.84780 s |

无 ACK 数包含初始启动/重启窗口，不能把全部 24 次都归因于自动确认复位。关键是状态查询丢 ACK 后未提前停止；最终由两次同代号 confirmed A 查询及 READY/ZERO=3、SD/MOE/CCER/FLAGS/FAULT 全 0 判定成功，不以启动日志代替确认。只提交一次试运行请求，不强制确认、不重发激活。

## ADC/FOC 与保护

同一停止会话 VTOR=0x08008000；完整 Flash 中 A 镜像与匹配 ELF 一致后，才解码 A 的 RAM 数据。

| 指标 | 实测 |
| --- | ---: |
| FOC timing frames | 685101 |
| FOC wall max | 5313 cycles = 31.25294 µs |
| FOC active estimate max | 31.25294 µs，含诊断开销 |
| FOC preempt max | 0 µs |
| >50 µs deadline miss | 0 |
| normal path max | 5313 cycles = 31.25294 µs |
| suspect path max | 3364 cycles = 19.78824 µs |
| unresolved path max | 3430 cycles = 20.17647 µs |
| CUR_CONFIRM enter / clear / fault | 270 / 270 / 0 |
| CUR_CONFIRM max cycles / elapsed | 2 / 101 µs |
| CLEAR_GOOD_SAMPLES / MAX_CYCLES | 2 / 4，未修改 |

ADC IRQ 最后串口观测 PAIRS=682904，MISS=0、PF=0；首次到末次 PAIRS 从 48849 增加到 682904，WORK 从 24366 增加到 653706。末次串口编码器 READS=32867，FAIL/TIMEOUT/IO/SCHED/STALE 全 0。停止抓取稍晚于末次串口查询，因此 RAM 计数略大，不能将不同时间点的计数当作同帧。

NVIC 实物清单通过：ADC=2；TIM2、RX DMA、TX DMA、TIM7=3；SysTick/PendSV=15。TIM2/RX DMA/TIM7 不抢占 ADC，编码器 deferred service=239779、RX events=65764、period count=32860、TX errors=0。低优先级 ISR 的 service wall 包含其被 ADC 抢占的时间，不能把它重新当成抢占 FOC 的时间。

deadline snapshot 未捕获且 valid=0，是本轮无超时所对应的预期结果，不是一次已发生超时的有效快照。

## 真实 CCR 与假设提交：分开报告

| 统计 | 实际 ADC 入口提交上一拍 pending | 假设本拍末尾提交 |
| --- | ---: | ---: |
| 测点 | 661099 | 656195 |
| 实际 CCR write | 661099 | 0 |
| late count | 0 | 17 |
| 最小 margin | 2559 ticks = 15.05294 µs | -468 ticks = -2.75294 µs |
| latch crossing / mixed latch | 0 / 0 | 不作为实际提交证据 |

实际 CCR 原始写事务 max=509 cycles=2.99412 µs；包含入口检查/测量的整个 pending commit path max=1104 cycles=6.49412 µs，pending generation max=1049 cycles=6.17059 µs。两者范围不同，不混用。

实际 margin 按当前 TIM1 center-aligned、ARR=4249、PSC=0、RCR=0、preload 配置和写入末端 CNT/DIR/DWT，估算到本次 ADC 入口后的目标 bottom latch 的剩余量，并扣除观测跨度；probe 没有修改 timer update 行为。真实物理 shadow latch 没有被外部仪器直接观察，结果只说明本次观测期间实际写事务有余量，不能证明所有工况 WCET。

原有粗粒度串口计数仍有 `ADC LATE` 和 `ADC COMMIT BOTTOM_LATE`，且 `READY=0/HW_VERIFIED=0`，本轮未关闭或修改它们；不能与上述新的 actual late 字段混为一谈，也未用本结果解锁原功率输出准入。hypothetical late=17 仍说明若回到本拍末尾提交会存在问题，不能将其误报为当前 pipeline 实际 late。

## 收尾

试运行 finally 关闭 SD/MOE/CCER 并停住 MCU，完整应用和私有 Flash 未变。用户确认 12 V 关闭后，通过正常 bootloader 流程恢复原 B 启动选择，未刷 B、未直接写 Flash 元数据；最后停在 B 入口：

- restore PASS，confirmed B、pending none、attempts=0、generation=615。
- VTOR=0x08040000、CPU halted、SD/BDTR/CCER=0。
- 完整 Flash SHA256：`270e1e887551c61cdc9826e242b017dfb66a6d86c7353a0780f9f2c9f00cbc2b`。
- `all_app_and_private_bytes_unchanged=true`，host motor commands=0。

下一次上板前应绑定本次 B615 恢复收据并继续完整基线核对，不能直接沿用已过期的 B611 代号重跑。

## 收据

- 暂存：`safety_backups/protected-closed-loop-20261014/encoder-health-stage-1792224841168627300.json`。
- 单次试运行：`safety_backups/protected-closed-loop-20261014/encoder-health-trial-1792224917335929900.json`。
- 恢复：`safety_backups/protected-closed-loop-20261014/encoder-health-restore-1792225057329032900.json`。

原始 Flash/RAM 留在 ignored private 目录，不公开上传。本轮没有修改 FOC 数学、PI、SVPWM、电流判别器、CUR_CONFIRM、一拍 pipeline、IRQ 优先级或保护阈值。
