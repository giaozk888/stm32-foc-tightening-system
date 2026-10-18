# TIM2 / RX DMA 降级与编码器事件 ISR 瘦身

## 范围与结论

只做离线修改、构建和测试。没有访问板子、串口、ST-Link，没有刷写、复位、启动电机或修改任何槽启动元数据。新候选为 A/B 的 `EncoderFocFirst`，继承已经验证过的功率硬关闭 `OneCyclePwmPipeline`；旧 preset 保留原样用于对照，不会默默替换旧实测镜像。

依据上轮同帧证据：54.435 µs wall = 34.594 µs active estimate + 15.947 µs TIM2 + 3.894 µs RX。本轮通过优先级关系消除后两者对 FOC 的**抢占**，不是屏蔽全局中断、降低采样率或调整判别/故障阈值。不能把 34.594 µs 当成本次新镜像的板测结果，也不能据此保证所有帧已经小于 50 µs。

## 1. 有效运行优先级

下表是完成应用初始化及 `ProtectedLoop_Init` 后本候选的有效值；数字越小越优先。HAL ADC MSP 的早期初值不等于运行 FOC 时的值。NVIC grouping 保持 3，即 STM32 的四位抢占优先级、无子优先级。

| IRQ / 路径 | 原 pipeline | 新候选 | 能否抢占 ADC=2 | FreeRTOS FromISR |
| --- | ---: | ---: | --- | --- |
| HardFault | 固定 -1 | 不变 | 能，异常路径 | 无 |
| TIM1 BREAK / BREAK2 | 当前未启用 | 未启用，不新增 | 不适用 | 不适用 |
| driver fault 独立外部 IRQ | 未发现本配置有独立启用的向量 | 不新增/不改接线 | 不适用 | 不适用 |
| ADC1_2 / FOC | 2 | 2 | 本体 | 无 |
| TIM2 编码器事件 | 1 | 3 | **不能** | 无 |
| DMA1 CH4 / SPI1 RX | 1 | 3 | **不能** | 无 |
| DMA1 CH5 / SPI1 TX error | 1 | 3 | **不能** | 无 |
| TIM7 software health | 3 | **3，不变** | 不能 | 无 |
| TIM6_DAC 编码器延后服务 | 未使用 | 4 | 不能 | 无 |
| UART LPUART1 | 6 | 不变 | 不能 | 非本次修改 |
| SysTick / PendSV | 15 | 不变 | 不能 | 原 RTOS 路径 |

ADC=2、TIM7=3 均冻结，二者之间没有可用整数优先级，因此编码器事件 IRQ 与 TIM7 **同级 3**，不是谎称它们严格排在 TIM7 之前。它们不能相互抢占，ADC 可以抢占全部编码器事件/服务路径。

`configPRIO_BITS=4`，`configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY=5`，`configMAX_SYSCALL_INTERRUPT_PRIORITY=0x50`。priority 0..4 禁止调用 FreeRTOS API。本次 TIM2/RX/TX/TIM6 和原故障 hook 没有 `xQueueSendFromISR`、通知/信号量 FromISR 或 `portYIELD_FROM_ISR`，不新增 RTOS 调用，故 3/4 合法。

硬件过流/BREAK 接线与开关均未新增或重新验收；不能把未启用的 TIM1 BREAK 描述为已经存在的最高优先级安全 IRQ。原 ADC 电流保护、原故障关断函数和异常关断保持原样，所有保护阈值不变。本候选本身仍编译为功率硬关闭。

## 2. TIM2 / RX ISR 原来与现在

原 TIM2 除清标志外，还同步执行 `AsDma_CheckDeadline`、`AsDma_Guard`、`AsDma_Begin`：包括 CS setup/hold/gap/BSY、两字协议推进、parity/ERRFL、结果完成发布、错误快照/复位，以及周期调度。原来**没有**角度浮点换算、unwrap 或速度滤波；这些已在 1 kHz `FOC_EncoderSpeedUpdate` 中，不虚构一次“浮点搬移”。

现在 TIM2 仅清 CC 标志、检查原绝对到期条件、记录事件序号并软件 pend 延后服务。正常路径不推进协议、不做 parity，不循环、不格式化。错误时只先直接关 MOE/AOE、拉低 SD，并锁存原因；原较重故障 hook 在延后服务执行。

原 RX ISR 检查 DMA/SPI 错误，调用 `AsDma_RxComplete`，做 deadline/BSY/guard 设置或错误快照清理。现在仅检查/确认 DMA、停本次 word 的 DMA 请求、保存 raw word 与 RX IRQ receipt timestamp，最后发布 data-ready sequence，并 pend 延后服务。TX 同样只处理发送错误。DMA/SPI 错误标志在 ACK 前保存，其他故障寄存器由延后服务读取，故 CCR 等字段可能已处于停止状态，不谎称全部寄存器都是 ACK 前快照。

原 engine 的 CS、parity、ERRFL、事务推进和最终发布放在 **priority 4 的 TIM6_DAC 软件 bottom half**。该向量在本工程配置没有其他使用者，初始化会拒绝已经启用的占用；不启动 TIM6/DAC 外设或额外采样时钟。采用已有 NVIC 空闲向量是为了在 ADC 下方服务，不占用 PendSV/SysTick。

这是把工作移出 TIM2/RX 顶半部，**不是把所有协议工作都移出全部 ISR**。2 µs 的 CS guard 和 200 µs 的事务预算不能挪到 1 kHz 任务后还声称满足原时序。1 kHz 任务中原有角度转换/unwrap/速度估计/滤波/预测不变。延后服务没有 busy-wait、drain/catch-up 循环、动态分配或 UART。

## 3. 为什么可能是 6 个 TIM2 IRQ

TIM2 仍是 1 MHz 时间基准，不是 1 MHz 角度采样器；角度事务周期仍为 1000 µs。无 BSY 额外延长的正常两字事务有：两次 setup、两次 hold、一次 gap；再加下一周期 compare，共可有 6 个 TIM2 服务。RX 两次对应两个 SPI word，不是两份独立角度。

`UIE` 没有启用；compare 标志确认、绝对 due 检查和禁止追赶采样 burst 保留。离线真实 engine 测试验证此序列以及 1 kHz attempts，不能因此宣称已外测每一个硬件 pending 原因；额外事件累计量留待人工板测核对。

## 4. 完整快照、预测与 stale

RX 顶半部只发布 raw/timestamp/error 的事件邮箱。协议确认完成后，序列化的 writer 将完整 `AsDmaSample` 写入未发布 bank，经 DMB **最后提交 generation**。失败状态也发布，不会让旧 OK 样本永久冒充新数据。

`AS5047P_DmaGetSample` / `AS5047P_DmaSnapshot` 新分支不关中断、不等待低优先级 writer。高优先级 reader 只能得到上一完整 bank；任务读者用 generation 前后校验，最多两次，拒绝跨两次 publication 的 ABA/撕裂。raw、sequence、timestamp 和 status 作为一份快照使用。旧启动/停止/ACK/故障路径的临界区保留，没有用新的全局屏蔽来解决优先级问题。

沿用原任务计算和 20 kHz prediction；没有新 observer，没有改 electrical zero、方向或 pole pairs。timestamp 沿用原“RX IRQ 软件接收时刻”约定，**不是硬件锁存的 SPI 物理采样时刻**；IRQ 延后会增加时间戳不确定性，未用回填/伪造旧时间补偿 CS guard。

常数保持：事务 200 µs、CS guard 2 µs、角度周期 1000 µs、sample max age 1500 µs、control watchdog 2500 µs。deadline 仍按当前实际服务时间判断；超过原预算仍 fault，不通过延长阈值掩盖饥饿。错误锁存只处理一次，旧 epoch RX 不能恢复取消的事务。

## 5. timing attribution 与冻结项

首个 deadline snapshot 的完整字段、valid-last 和不覆盖语义保留。新配置的 TIM2/RX/TX/TIM7 均低于 ADC，其 service wall 可能**包含 ADC 子中断**，不能再从 ADC wall 中相减。新 Stamp 分支只在 NVIC inventory 证明该前提、且没有未知更高优先级外部 IRQ 时，认定这些源的 FOC preemption delta 为零；优先级配置错误仍标无效，不伪造有效归因。

IRQ 累计调用数/时长保留，任务打印明确标成 `SERVICE_WALL_INCLUDING_CHILDREN`，不叫抢占 CPU 时间。`wall`、`active_est`、deadline miss 和第一帧 snapshot 保留；active estimate 包含插桩/异常成本，不是纯数学 WCET。heavy profiling 的 ON/OFF 开关仍可用。

没有修改 ADC ISR、入口 CCR commit、一拍 pending、latch/margin probe 或 PWM 寄存器行为。以修改前保存的 SHA256 回归冻结 pipeline、ADC timing、current discriminator、CUR_CONFIRM、protected control binding 源文件。没有修改 main 中 PI/速度/位置/拧紧/角度预测，也没有改 CAN/Pigweed/IAP/A-B。

历史 `OneCyclePwmPipeline` 对照 A BIN 重建 SHA256 仍为 `ce8cacaf9e106d0c80c980cbcd63a0410110dab32fb59c4e4bac0a51a7008a70`，与上次实测固定镜像相同。新候选只给编码器端口单元使用 `-Os` 以放入原槽，不更改 FOC 数学单元的优化选项或 Flash 分区。

## 6. 构建、测试与上板边界

17 个相关配置全部构建通过：基础 Debug；A/B 的 FastCurrentReject、ComputeOnly、FastPathTiming、PreemptCommitProbe、OneCyclePwmPipeline；A/B 的 pipeline heavy=0 对照；A/B 的 EncoderFocFirst heavy=1/0。127 项 unittest 全部通过，包含既有 CUR_CONFIRM、保护、pipeline、margin、deadline attribution 回归及新编码器回归。新测试还分别以 -Os/-O2 编译运行 A/B 原 protocol / transaction / DMA engine fixtures。

同源 warning-delta 检查通过：新候选相对旧 pipeline 没有新增源码告警；仍有已有 unused-function / unused-variable 和 RAM 可执行段的 RWX 链接告警，不宣称工程零告警。新共享驱动/归因源码没有新增 warning/error。

| 新候选 | Flash load bytes | RAM linked bytes | 剩余 Flash / RAM bytes |
| --- | ---: | ---: | ---: |
| A heavy=1 | 228964 | 129064 | 412 / 1944 |
| B heavy=1 | 227956 | 129048 | 1420 / 1960 |
| A heavy=0 | 226100 | 127088 | 3276 / 3920 |
| B heavy=0 | 225084 | 127072 | 4292 / 3936 |

A 诊断镜像 Flash 余量仍很小，没有扩大原 224 KiB 槽或 RAM 边界。heavy=0 是单独构建目录，不是修改已用于取证的 heavy 镜像。

完整离线收据及逐配置日志：`tests/foc_adaptive_build/encoder_foc_first_evidence/receipt.json`。

- A heavy BIN SHA256：`05457edae53ac0be14d702c24a8a99857f4b2d6c2df28fa8a5eb47c1a10a2b75`。
- A heavy ELF SHA256：`ed504711d5bd424178584c89d5172f405cb1bea75ee91b69a6b38f6f70446ecc`。
- B heavy BIN SHA256：`1ce8ca99bbd714dd6c4d67b09df6bb4148d2a5b04db5e91efaa69d0bd1a4f1df`。

新的测试覆盖：完整发布与抢占 writer、任务读者 ABA/有限重试、generation wrap、失败发布；真实 deferred include 配合原 engine 的两字协议、延后/超时/控制 stale、parity、DMA error、故障中被顶半部打断、旧 epoch；全部 50 个相位的理想化 35/50 µs ADC blackout 模拟；低优先级半发布账本不污染 ADC 归因、错误 NVIC 被拒绝。blackout 仿真不是实际 ISR WCET，也不能代替板测事务耗时。

人工上板应选择新 `EncoderFocFirst` 镜像及匹配 ELF，不得沿用 pin 旧镜像 hash 的板测脚本冒称测了新版本。目标仍为 TIM2/RX 对 FOC 抢占 0、FOC miss 0、actual CCR late 0，另核对编码器事务/guard 延迟、age 和原保护仍有效。新路径是否达到这些数值尚未实测。

本轮没有读取/恢复现场启动选择。上次停止时的 pending/confirmed 待恢复事项仍以原板测收据为准，不能因本次编译就认为已恢复 B。

TIM2/RX DMA priority + encoder ISR slimming 已完成，等待人工上板验证
