# CUR_CONFIRM 周期确认上板验证（2026-10-17）

## 结论

**本次功率硬关闭的 CUR_CONFIRM / ADC / FOC 计算验证通过。**

正常健康确认后观察 31.5236 秒，无运行故障、无 50 us FOC 计算 deadline miss。
244 次进入 CUR_CONFIRM 全部清除，最大确认历时 115 us，最大确认周期数 2；没有再因为超过旧的 100 us 而触发 CUR_CONFIRM 超时。

本次没有启动电机、没有开启功率桥，也没有验证硬件过流实际关断时序或带电闭环性能。PWM 更新余量告警仍存在，不在本轮修复范围。

## 镜像及测试条件

使用 `foc2_app_a/build/FastCurrentRejectComputeOnly/foc2.bin`，227492 字节：

```text
BIN SHA256 1cbe43061f7879e5550d0db9301c739c2e00ca213e1ec1a3acb12e3fff5a0bdf
ELF SHA256 386a5dea822b590e50d2b75ab1f2c72148883b219223dc11360650470c706fc7
```

运行时身份：`NAME=FAST_CURRENT_REJECT HARD_OFF=1`、`METHOD=TWO_SAMPLE`、`OC=RAW_CONFIRM_4 TRIP_MA=4000`。
没有更改上一轮离线测试通过的固件，也没有修改 PI、SVPWM、判别器、保护阈值或 PWM/ADC 频率。

用户确认驱动板先断电、MCU 保持供电、动力线断开；暂存完成后按提示开启驱动板 12 V，保留原限流与信号接线。试验结束再次关闭 12 V。

## 实测数据

从停住时保存的完整 SRAM，按固定新版 ELF 及 ARM 编译得到的结构体布局回读：

| CUR_CONFIRM 统计 | 实测 |
| --- | ---: |
| `cur_confirm_enter_count` | 244 |
| `cur_confirm_clear_count` | 244 |
| `cur_confirm_fault_count` | 0 |
| `cur_confirm_max_cycles` | 2 |
| `cur_confirm_max_elapsed_us` | 115 us |
| 最终 `pending / good_samples / confirm_cycles` | 0 / 0 / 0 |

进入后允许的预算仍为 4 个新 ADC 周期。本次自然输入只用到了 2 周期清除路径，没有在实物上制造 4 周期耗尽故障；第 4 周期故障边界及最后周期成功边界已由此前离线状态机测试覆盖。

确认统计位于 `cl_safety`（0x20005bc4）的匹配布局中。ARM 布局为：

```text
sizeof(FocFeedbackSafety) = 300
pending / good_samples / confirm_cycles offsets = 116 / 117 / 119
five statistic offsets = 124 / 128 / 132 / 136 / 140
```

仅适用于上述固定 ELF，不可用于其他版本 RAM。

整轮最终 FOC profiling RAM（`cl_current_cycles`，0x20005a60，36 字节）：

| 指标 | CPU cycles | 170 MHz 换算 |
| --- | ---: | ---: |
| FOC 总最大 / 正常路径最大 | 7150 | 42.0588 us |
| 可疑路径最大 | 5697 | 33.5118 us |
| 未决路径最大 | 4197 | 24.6882 us |
| 50 us deadline miss | 0 | 0 次 |

周期性串口统计中的峰值和停机后 RAM 中的最终峰值一致。这里使用完整最终 RAM 回读值，不将整数 `MAX_US=41` 与完整 DWT 峰值混为同一个测量边界。

末次只读状态：

- `FAULT=0 FLAGS=0`，无首故障快照（`valid=0`）。
- `SD=0 MOE=0 CCER=0`，输出一直锁定；主机 START 数量为 0。
- 零点状态 `STATE=3 REASON=0 N=4000 U0=1562 V0=1561`。
- 原码零点资格仍为 `RAW_STATE=4 RAW_REASON=2`，不能据本轮宣称原码噪声已消失。
- ADC 计数 `PAIRS=682827 MISS=0 PF=0`；该累计还包含校准/查询等阶段，不用于反推精确采样频率。

## 保留的问题和验收边界

- 末次 `ADC COMMIT` 仍显示 `BOTTOM_LATE=20313 HW_VERIFIED=0 READY=0`，对应 ADC 查询也有 LATE 计数。**FOC 计算小于 50 us 不等于物理 PWM preload 更新时限已经验证。** 本次未改变相关计划/更新逻辑。
- 诊断缓冲显示 `DROP_B=3 DROP_S=768`，工作任务栈余量 1872 字节。诊断缓冲丢弃与 ADC pair `MISS=0` 是不同计数，不能据本轮声称全链路零丢弃。
- 五项确认统计是健康确认触发复位之后本次启动期间的统计，不累计跨复位的首次 5 秒健康窗口。
- 硬件过流/故障优先级与 ADC 断流链保留，本次未人为注入硬件过流、断流或真实大电流。
- 不认定本次完成电机转动、速度环、扭矩或工业拧紧精度验收。

## 操作与证据

本轮新增独立上板入口 `tools/cur_confirm_cycles_board_test.py`，不改历史脚本的固定镜像身份。
默认只离线验证镜像和布局；写入/试运行/恢复需要分别指定操作和实际供电阶段。
控制台只允许查询和 `ANALOG SAFE`，拒绝 START、FW END、强制确认、清故障等命令。

先前完整备份受权限限制；通过权限审批读取并比对，未更改备份目录 ACL。完整 Flash / SRAM 仍留在忽略跟踪的私有目录，没有上传到网络或 GitHub。

操作收据位于 `safety_backups/protected-closed-loop-20261014/`：

1. `cur-confirm-restore-prior-1792202031522504900.json`：通过原 bootloader 恢复已确认 B，元数据 generation 588，停在 B 入口。
2. `cur-confirm-stage-1792202065811165900.json`：仅写入非活动 A，完整回读一致，A 擦写页之外全部不变，未激活。
3. `cur-confirm-trial-1792202130676075100.json`：仅一次 A 试运行，正常 5 秒健康确认，确认后观察 31.5236 秒；完整 Flash 比对表明应用及私有区域未变。RAM 所有者 VTOR 同会话确认为 A。
4. `cur-confirm-restore-1792202223657456700.json`：通过原 bootloader 恢复原 B 启动选择，generation 592，停在 B 入口；应用及私有区域未变。

主机 UART 试运行提交为 0、主机电机启动为 0；一次试运行由现有 bootloader SRAM 请求完成，应用健康检查自行确认，无强制确认或自动重试。

上板入口额外 5 项离线测试通过，覆盖固定镜像、ARM 布局、确认与最终 FOC 周期解码、拒绝启动命令及恢复收据路径限制。`tests/foc_cur_confirm_layout.c` 仅用于离线编译解码布局，不链接进入固件。

注：复用的历史底层工具会打印旧版本名称（例如 B576 或 deferred shadow）；验收以本轮固定 SHA、实际运行时 profile、元数据和完整回读结果为准，不以历史提示文字作为版本识别依据。

## 最终状态

驱动板 12 V 已由用户关闭。原 B 启动选择已恢复，pending / attempts 为 0。
CPU 停在 B 入口，`SD=0 BDTR=0 CCER=0`，没有运行 B 应用或再次启动测试。
新的功率关闭 A 镜像保留在槽内，但没有待执行的 A 试运行请求。
