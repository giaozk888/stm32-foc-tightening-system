# 编码器终态仲裁修复：Rs50单次板测

本轮用户授权单次验证，分别确认12V关闭/MCU供电/台架锁轴/外壳固定防护/
原接线/12V限流0.5A；完整回读后再确认ON无报警且现场可立即断电。
仅更新非活动A，保留B回退。只发1次RS50，不START、不重试、不升档。

## 镜像/脚本

- preset `MotorParameterIdentificationEncoderTerminalDiagnostic`；BIN214764B、motor_ident ABI1740B。
- BIN SHA256 `2e0661646b6bedc372c7d7f4209e4dc4f5279f23a1082f0d9992c680b11c7b2f`。
- ELF SHA256 `6a55c7148828a5eb613dcb26dfa969b24eed9d7ec99091b5cb021c47bd1d261a`。
- 独立pinned runner `tools/motor_ident_encoder_terminal_board.py`核验B832基线、
  driver编译AS5047P_DMA_TERMINAL_FIX1和FOC_FIRST1、terminal_claimed符号4B、
  原保护及Rs策略、候选BIN/ELF/ABI。所有编码器状态仅从停止后的RAM读取。
- 3项新脚本测试、全部motor-ident相关53项测试通过。
- stage `tmp/motor-ident-rs50-stage-1792502215235700100.json` PASS：
  完整独立回读，原B/boot/private/metadata未变。
- run `tmp/motor-ident-rs50-run-1792502267845988100.json`。

## 结果：未完成辨识，真实HOLD阶段超过200us

校准/时序/任务栈预检通过，RS50明确ACK。运行约33.5ms退出，
终态MID_PROTECTION1、N0。原保护FLAGS48包含CL_BAD_ENCODER32和CL_BAD_OUTPUT16。
顶半部先DeferOff关闭SD/MOE后，ADC可能先观察输出门状态不一致，因此该组合与
原即时关断路径一致；不能据此声称另有独立驱动板报警。

### 与上一轮重复终态不同的关键证据

| 本次失败事务 | TIM2 us | 相对started |
|---|---:|---:|
| started | 8030628 | 0 |
| 最后RX top timestamp/word_rx | 8030782 | 154 |
| deadline | 8030828 | 200 |
| HOLD guard due | 8030829 | 201 |
| TIMEOUT发布/快照 | 8030831 | 203 |

first_fault：valid1/statusTIMEOUT2/phaseHOLD4/frame1/IPSR70。
engine attempts6537、successes6536、failures1，符合每次attempt只有1终态；
没有上一轮attempts==successes但又多1failure的现象。

Publication两bank：

- 上一次事务：OK、seq6536、sample_us8029732、completed8029782、elapsed154。
- 本次事务：TIMEOUT、seq6537、sample_us8030782、completed8030831、elapsed203。

两者是不同事务，不是同一事务成功后又超时。
`same_attempt_success_then_timeout=false`。
本次截止到来时，HOLD guard本身就要到第201us，晚于200us，不能合法判成功。
这表明竞态修复候选没有吞掉真实未完成事务的超时，但一次短测不能证明所有交错均已资格化。

RX top在154us取时，最后HOLD guard到201us；依据生产代码2us guard可知
最后进入/重设HOLD约在199us。中间约45us可能包含deferred排队或BSY/guard推进，
未保存逐阶段事件时戳，不能唯一归因为ADC抢占或硬件BSY。
没有DMA error、schedule miss、control stale，timeouts1。
SPI/DMA寄存器是停止后故障快照，不可倒推每个早期中断的硬件状态。

本轮未调大200us、未改priority/guard、不修改固件后自动重试。

## 辨识/FOC状态

| 项目 | 值 |
|---|---:|
| current reject / good / max run | 12 / 656 / 1 |
| total reject stop | OFF |
| Rs gap events / skipped / max | 3 / 3 / 1 |
| Rs timing snapshot valid | 0 |
| FOC max | 35.4588us |
| deadline miss | 0 |
| actual CCR commits / late | 134199 / 0 |
| actual min margin | 15.3412us |
| CUR_CONFIRM enter/clear/fault | 44/44/0 |

200ms稳态记录尚未开始，N0不能计算Rs。
不是电流累计拒绝、连续3对异常或Rs100us间隔规则触发。

## 后处理与收尾

先STOP/ANALOG SAFE、保存Flash/RAM并halt，用户再次确认12V关闭后恢复原B启动选择。
restore `tmp/motor-ident-rs50-restore-1792502360728781200.json` PASS：
confirmed B836、pending0、SD/BDTR/CCER0，MCU停在原B入口；B/boot/private和候选A字节未变。
不执行B应用，不再注入电流。

`tools/encoder_saved_fault_report.py`的说明文字改为依据布尔证据区分重复/非重复，
并将同一事务success_margin与上一事务last_success_margin分开。
原始run收据不改；纠正后的派生报告 `tmp/encoder-terminal-board-analysis.json`。
新增本次保存数据回归，旧竞态复现/旧证据与新HOLD超时共3项诊断测试通过。

## 下一步

需先测清编码器最后RX、deferred service、BSY/HOLD guard的排队耗时，
减少真实事务在FOC负载下逼近200us的情况；不是继续绕过编码器保护。
当前结论：原重复终态未在本次复现，但完整Rs辨识仍未通过。
