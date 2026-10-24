# No-travel-exit Rs 50 mA 单次板测

现场分别确认 OFF、锁轴夹具/固定/防护/接线及12V限流0.5A，之后确认ON无报警且可立即断电。
只执行一次 `MOTOR TEST IDENT RS 50 LOCKED CONFIRM`，没有 START、自动重试、升档或 Ld/Lq。

## 镜像和流程

- preset：`MotorParameterIdentificationNoTravelDiagnostic`
- BIN SHA256：`dedb650aa982ab0b565141e02ec311f6891e6d53a4644c476237268a87e9c8c0`
- ELF SHA256：`3878b129ca61a51e60d3b67c3f15ffb3fc9602be41de29812cc881d28fc5c250`
- A BIN 213580B，motor_ident ABI 1660B；正式B字节不变。
- 独立精确镜像/B812基线适配器：`tools/motor_ident_no_travel_board.py`。
- 新增3项无设备脚本测试全部通过：镜像/基线、单次RS50和关闭输出后读出、错误版本拒绝。
- stage：`tmp/motor-ident-rs50-stage-1792498686372336700.json`，完整回读通过，B/boot/private/metadata不变。
- run：`tmp/motor-ident-rs50-run-1792498739966089600.json`。

## 结果

校准和时序预检通过，RS50指令仅发送一次，明确ACK。终态：STATUS=4、REASON=8
（MID_TIMING），N=0；REJECT=0、GOOD=1、MAX_RUN=0、FIRST=0。
UART实读 `TRAVEL_EXIT=OFF`，因此不是0.10度位移退出，也不是电流拒绝触发。

RAM：start_us=7982292，last_us=7982297，last_seq=157280。
现有连续性条件是seq增量必须1且时间差45–55us；失败点自身seq/dt没有锁存，
故只能确认条件不满足，不能进一步断言是序号间断、间隔抖动或物理ADC丢样。
这是辨识诊断退出，不是FOC 50us超时；本次未改变这个条件。

| 项目 | 结果 |
|---|---:|
| FOC wall max | 30.7647 us |
| deadline miss | 0 |
| actual CCR commits | 133240 |
| actual CCR late | 0 |
| actual minimum margin | 13.5765 us |
| CUR_CONFIRM enter / clear / fault | 56 / 56 / 0 |
| 原保护 first_fault.valid | 0 |

有效参数窗口为空，不能计算/报告有效Rs，更不能继续Ld/Lq或更新PI。
诊断停止后先MOTOR TEST STOP/ANALOG SAFE，再读取记录；调试器保存Flash/RAM并停住。

## 收尾

用户再次确认12V关闭后，原bootloader流程恢复B启动选择，不执行B应用。
restore：`tmp/motor-ident-rs50-restore-1792498798399003500.json`，PASS；
B/boot/private和A候选字节保持，输出关闭、MCU停在B入口，motor_commands=0。
没有后续自动复测。后续应先对辨识连续性判据采集失败seq/dt并区分Rs稳态与L瞬态需求，
不能把此次失败解释为Rs测量通过。
