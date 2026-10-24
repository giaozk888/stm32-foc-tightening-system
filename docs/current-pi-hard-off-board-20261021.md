# 新电流 PI 功率硬关闭预检：协议中止，未注入电流

本次不是新旧 PI 实机阶跃性能比较；只运行了新 PI 的功率硬关闭计算镜像，无 START、无辨识电流注入、无拧紧动作。

## 证据

- A：`CurrentPiIdentifiedComputeOnly`，228788 B。
- BIN SHA256：`e8541fa04c7b8a9cf1b9df2f00d42dbef0b03273bb467879235a26cea5f1c514`。
- ELF SHA256：`5309493fbbe4b3a9079e92ac90d5471b5f603a20b6d2d4dd94c4f632ce2a58b9`。
- 暂存：`tmp/current-pi-hard-off-stage-1792565210881353700.json`，双完整回读通过，原 B872 和配置未变。
- 试运行：`tmp/current-pi-hard-off-run-1792565379314959400.json`，原始收据保持失败，不因离线解析修复而改成 PASS。
- 回退：`tmp/current-pi-hard-off-restore-1792565516499442800.json`，成功恢复 B876，pending=0，停在 B 入口，B 应用未运行。

## 实测观察

新 A 通过 5 秒试运行健康窗口并经 bootloader 正常自动确认复位。确认后脚本在读取零点回复时中止，尚未完成完整预检。

同次 Flash/RAM 与精确 ELF 核验后保存的确认复位后短窗口：

| 指标 | 结果 |
|---|---:|
| FOC wall max | 30.9059 µs |
| >50 µs deadline miss | 0 |
| 实际 CCR commit | 26153 |
| CCR late | 0 |
| 最小 actual margin | 19.4353 µs |
| CUR_CONFIRM enter / clear / fault | 6 / 6 / 0 |
| 首次故障快照 valid | 0 |

这些不是长时间时序验收结果，也不是通电电流阶跃响应；不能据此宣称新 PI 实机优于旧 PI。

实际零点回复：

```text
STATE=3 REASON=0 NOM=1561 U0=1561 V0=1563 N=4000 RET=0
RNG=1555:1566,1556:1571 RAW_STATE=4 RAW_REASON=2
```

该独立计算夹具使用历史中值零点报告格式，运行零点 STATE=3 通过；原码对照 RAW_STATE=4/RAW_REASON=2 单独保留，不能隐藏，也不能把它当作当前运行零点失败。它不是最新 robust-admission 字段格式，不能凭空补造 valid/reject/total 统计。

## 中止原因和脚本修复

1. 脚本误用最新 robust-admission 的解析器，强制要求 `valid/reject/total/...`。当前夹具回复缺少这些字段，触发 `Incomplete zero-admission report`。这不是板端新 PI 保护故障。
2. 清理阶段错误通过只读 query 发送 `MOTOR TEST STOP`，被主机 Console 的允许列表拒绝。独立调试器清理仍成功，已关闭 SD/MOE/CCER 并停住 MCU。该错误没有导致电机运行，但确实使串口清理未完整执行。

已仅修复主机脚本：按实际协议版本解析零点；清理使用已允许的 `cleanup_command('STOP')`、`cleanup_command('ANALOG SAFE')`，即使 STOP 无应答仍尝试 ANALOG SAFE；最终始终保留调试器紧急关闭。新增测试同时禁止用正常 RAM 时序数值把不完整预检升级为通过。

脚本 8 项离线测试通过（`tmp/current-pi-preflight-script-tests.log`），无设备操作的默认模式验证通过。固件未因这些脚本修复而改变，未自动重试。

## 最终状态

用户已确认 12 V 关闭。恢复收据确认：B876、无 pending、B 应用未运行，VTOR=0x08040000，MCU halted，SD=0、BDTR=0、CCER=0。A/B 应用、bootloader、私有配置保持不变，只有原官方流程的启动元数据更新。

下一步需另行人工启动修复后的预检，通过后才能准备50 mA电流短测。尚无新旧 PI 的实机电流对比结论。

## 人工重测：仍因主机适配中止（不改写原收据）

- 同镜像核验：`tmp/current-pi-hard-off-stage-1792565742069669100.json`，未重刷，双回读通过。
- 重测：`tmp/current-pi-hard-off-run-1792565813793821900.json`，pass=false。
- 恢复：`tmp/current-pi-hard-off-restore-1792565911926092400.json`，pass=true，B880、pending=0，停在 B 入口。

本次零点解析已通过：STATE=3、REASON=0、N=4000、U0/V0=1559/1563；原码对照仍 RAW_STATE=4、RAW_REASON=2，未隐藏。新 A 也通过原健康确认流程。

确认复位后的最终 RAM：FOC max=30.9941 µs、deadline miss=0、actual commit=187024、actual min margin=19.3471 µs、actual late=0、CUR_CONFIRM=67 enter/67 clear/0 fault、first_fault.valid=0。

中止原因是脚本沿用了另一种轻量配置的“5秒必有四条时序打印”前提。当前镜像 HEAVY_PROFILE=1，`FocPreempt_Monitor` 明确可在并发拷贝被ADC打断时放弃打印；保存的 UART 没有这四条消息，无法据此断言板端保护失败。也不能把未完成的主机门禁自动改成通过。

另一个脚本错误是误以为 TokenConsole 具有 `cleanup_command` 方法；实际继承的 `pipeline_closed_loop_trial.Console` 只有受允许列表限制的 `query`，支持 STOP 和 ANALOG SAFE。两次实验均由独立调试器确认关断并停机，未注入电流。

本次仅修正主机：

1. 使用实际支持的 `query('STOP')` 和 `query('ANALOG SAFE')`，两者独立尝试，之后仍保留调试器关断和快照。
2. 功率硬关闭观察改为5秒内至少8次新鲜READY/SD=0/MOE=0/CCER=0回复，不以可选Monitor打印当强制接口。
3. 停机后必须用同次Flash/RAM及精确ELF校验原阈值：FOC<50 µs、deadline miss=0、actual late=0、actual margin>1 µs、CUR_CONFIRM fault=0，且实际commit不少于100000次。未完成观察仍不可仅凭RAM改判通过。
4. 新增针对实际Console类的模拟传输回归，避免无规格Mock虚构不存在的方法；回放本次保存的失败收据必须仍为失败。

11项脚本离线测试通过。固件未改变，未自动重试、未追加注入。用户确认12 V关闭后，仅恢复B880，SD/BDTR/CCER=0、MCU halted、B应用未运行、A/B/boot/private字节未改。后续重试需要新的人工上电状态。

## 再次人工重测：功率硬关闭预检通过

- 暂存核验：`tmp/current-pi-hard-off-stage-1792566155015279900.json`，无重刷、双回读通过。
- 运行收据：`tmp/current-pi-hard-off-run-1792566212259337300.json`，pass=true。
- 原bootloader健康试运行与自动确认复位正常；确认后观察5秒窗口，9次READY/输出关闭回复通过，首末回复时间分别为观察起点后0.083/4.578秒。
- 零点：STATE=3、REASON=0、N=4000、U0/V0=1560/1563。原码对照RAW_STATE=4/RAW_REASON=2仍保留，未掩盖、未改变原保护。
- 本镜像运行档位为 `FAST_CURRENT_REJECT HARD_OFF=1`，未发送START或电流辨识命令。

停机后同次Flash/RAM及精确ELF统计：

| 项目 | 实测 |
|---|---:|
| FOC wall max | 30.9588 µs |
| deadline miss | 0 |
| actual CCR commit | 126274 |
| actual CCR late | 0 |
| actual minimum margin | 19.3471 µs |
| CUR_CONFIRM enter / clear / fault | 60 / 60 / 0 |
| first_fault.valid | 0 |

串口清理两步均有应答：`OK STOP QUEUED`、`OK ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0 RESET_TO_EXIT=1`。调试器再确认SD=0、MOE/AOE=0、CCER=0及MCU halted。此次仅确认独立功率硬关闭计算夹具预检通过，不是闭环电流阶跃比较，也不是正式tightening全部功能验收。

尚未进行50 mA新旧PI对照，不能用本次0 A计算时序宣称新PI动态性能改善。
