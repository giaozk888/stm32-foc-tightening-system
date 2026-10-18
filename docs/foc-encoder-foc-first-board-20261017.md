# EncoderFocFirst 上板验证（2026-10-17）

## 当前进度：单次试运行失败，已完成故障取证并恢复原 B

用户确认驱动板 12 V 关闭，MCU 供电、U/V/W 动力线断开、IU→PA0／IV→PA1 不变。本轮没有发送 START，不启动电机。

1. 先用历史镜像绑定的 runner 恢复上轮 pending A 到原已确认 B，停在 B 入口。正常 bootloader 请求，无强制确认、无直接 Flash 元数据写入。恢复后 generation=604，confirmed B / pending none / attempts 0，SD=0、MOE/AOE=0、CCER=0，CPU halted。
2. 以此恢复收据作为严格基线，只写非活动 A，保留原 B 镜像、bootloader、槽外和私有配置。全 Flash 前后比较、镜像回读、末页擦除尾部及元数据检查全部通过。新 A 尚未激活。

收据（含私有备份路径，不发布原始 Flash/RAM）：

- `safety_backups/protected-closed-loop-20261014/deadline-attribution-restore-1792220106010424600.json`
- `safety_backups/protected-closed-loop-20261014/encoder-foc-first-stage-1792220243234471800.json`

## 本次绑定的镜像

- A BIN：`foc2_app_a/build/EncoderReview/EncoderFocFirst/foc2.bin`，228964 bytes。
- SHA256：`05457edae53ac0be14d702c24a8a99857f4b2d6c2df28fa8a5eb47c1a10a2b75`。
- ELF SHA256：`ed504711d5bd424178584c89d5172f405cb1bea75ee91b69a6b38f6f70446ecc`。
- 离线构建收据固定为 17 配置、127 测试；本轮重跑编码器 6 项与新板测门禁 4 项，全部通过。
- 独立 runner：`tools/encoder_foc_first_board_test.py`，沿用原完整回读/断电分阶段/单次试运行/故障停止/正常回退事务，不覆盖历史 runner。
- 解码器：`tools/encoder_foc_first_report.py`，TIM2/RX/TX 账本标为 service wall（可能包含 ADC 子中断），不得把它们当作抢占 CPU 时间相减。

## 继续测试的边界

用户随后回复“开了”，按原不变接线与断开动力线条件，已提交且仅提交一次新 A 的普通 bootloader 试运行，测功率硬关闭的 ADC/FOC。

目标：NVIC inventory 证明 ADC=2、TIM2/RX/TX=3、TIM6 software service=4；TIM7=3 不变。TIM2/RX 对 FOC 抢占为零、FOC deadline miss=0、actual CCR late=0、实际 margin 有余量，编码器按原时限工作。

试运行结束须锁定输出、停住 MCU；12 V 关闭后恢复原已确认 B 启动选择，不自动重试或启动电机。

## 本次实测：未通过，健康检查的优先级预期未同步

试运行收据：`safety_backups/protected-closed-loop-20261014/encoder-foc-first-trial-1792220326858495400.json`。

- 确实运行新 A：同一停止会话 VTOR=0x08008000，完整 Flash 与新 BIN/ELF 一致。
- 实际 NVIC：ADC=2，TIM2/RX/TX=3，TIM7=3；inventory ok=1、unexpected=0。
- 在启动校准阶段触发保护，第一故障 snapshot `protection_flags=128`，即 `CL_BAD_TIMER`。随后汇总 flags=140，校准未完成。
- 静态定位：`ProtectedLoop_TimerHealthy()` 仍在 `AS5047P_DMA_IRQ_PREEMPT_ADC` 分支把 `encoder_priority` 固定为 1，而新 profile 同时启用 FOC_FIRST 并已将 TIM2/RX/TX 改成 3。因此运行配置正确落在新优先级，但旧健康检查拒绝它。这是漏适配的健康检查一致性问题，不是本次发现真实 CCR late-write。
- 只有一帧 ADC 诊断，wall=13.676 µs，normal FOC exec=0、pending generated=0、actual CCR writes=0。**不能把 13.676 µs 当作 normal FOC max，也不能把 late_count=0 当作 PWM deadline 验收通过。**
- IRQ 顶半部 service wall max：TIM2 0.871 µs、RX 1.294 µs；样本数量有限且不含正常 FOC 运行负载，不能当作最坏执行时间保证。
- 编码器启动读取21次，FAIL/TIMEOUT/IO/SCHED/STALE均0，MAX_US=32；没有进入周期运行（period_count=0），不能验收持续获取与 stale 行为。
- CUR_CONFIRM 0 enter / 0 clear / 0 fault，未覆盖；阈值仍2/4，未修改。
- SD=0、MOE=0、CCER=0，host_motor_commands=0；完整应用/私有 Flash 未变，CPU halted。

本轮没有为绕过检查而修改健康判据、控制数学、阈值或重试。后续修复应只让新 profile 的健康检查预期与已选 NVIC 层级一致，仍拒绝错误优先级，并补运行级回归；旧 profile 预期保持不变。

用户已回复关闭12 V，已只恢复原已确认 B 的启动选择并停在 B 入口；不再试运行。恢复收据 `safety_backups/protected-closed-loop-20261014/encoder-foc-first-restore-1792220405035807300.json`：PASS，SD/PWM关闭、CPU halted，应用和私有配置字节不变。
