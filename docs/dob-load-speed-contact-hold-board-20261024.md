# 接触保持 V2：一次人工制动板测

本轮只更新非活动 A，执行一次240 rpm普通START。用户确认12 V关闭、制动器释放后，已恢复原B启动选择；不再运行。
未修改正式B、配方、PI、DOB增益、补偿限幅、采样、IRQ或保护。无自动重试。

## 镜像与准备

- A：`DobLoadSpeedContactHoldCandidate`，228712 B。
- BIN SHA256：`e9a96e62db1569272412e2363e3ea415c51f0e9888fcb2cc32b2681724dae90c`。
- ELF SHA256：`b7e5f39336399fe2196d3ec1407771336523beab6b0bc755ab6e02dda6aeb237`。
- 新板测脚本 `tools/dob_load_speed_contact_board.py`／V2解码，4项入口回归通过；旧V1镜像和脚本保留。
- 暂存记录：`tmp/dob-load-contact-stage-1792846667883233200.json`。两次完整回读通过，B／boot／配置／metadata未变，暂存时未激活、motor_commands=0。
- 原限制：240 rpm、总Iq±0.50 A、DOB增益0.25／补偿±0.025 A、500 rpm超速、20000°行程、8 s rundown、12 s板端限时。
- 上电零点校准通过：4000有效点、46拒绝点，零点IU=1559／IV=1563 ADC计数。预检栈余量2504 B，仅为预检时刻，不能当成全程最差栈余量。

## 结果与覆盖范围

运行记录：`tmp/dob-load-contact-run-1792846770893941900.json`。

| 指标 | 结果 |
|---|---:|
| START次数／观察周期 | 1／8000 |
| 选择120 rpm周期 | 694，约0.694 s |
| 策略事件 | 2条，完整保留，无覆盖 |
| DOB有效率 | 6528/8000，81.60% |
| 新鲜补偿更新率 | 6435/8000，80.44% |
| Iq命令峰值 | 0.50 A |
| 固件Iq测量统计峰值 | 1.186 A，不能解释为IqRef限幅后的电流上界 |
| DOB补偿峰值 | 24.258 mA |
| Iq限幅计数 | 234个周期 |
| FOC最大／deadline miss／CCR late | 33.194 µs／0／0 |
| CCR最小实际余量 | 15.165 µs |
| 独立保护故障 | 0 |
| CUR_CONFIRM | 进入137／清除137／fault=0 |
| 最终过程结果 | RUNDOWN_TIMEOUT，CONTACT=0，未完成拧紧 |

切换事件以下相对板端观测开始计时，来自完整V2事件记录：

1. **2.347999 s**：RUNDOWN中，高负载／上升趋势，均值69.36 mA、有效确认30988 µs，目标240→120 rpm。
2. **3.042026 s**：LIGHT／下降趋势，目标120→240 rpm；切换前原S曲线仍约125.616 rpm、加速度−105.973 rpm/s。
   目标恢复不等于实际速度瞬时恢复240；UART约3.13 s仍记录122.6 rpm，随后逐步恢复。

UART补充FSM记录在主机START后约**5.2585 s**观测到CONTACT_CONFIRM，已处于该状态48 ms，CONTACT_CONFIRMED=0；后来退回RUNDOWN。
两种时基不同，UART查询不能作为精确进入时刻或制动触发真值。
关键是：完整事件日志没有CONTACT_HOLD／CONTACT_REACQUIRE，降速选择在这次接触候选之前已释放。因此：

**本轮证明新A可完成原校准／预检／运行／关断，负载降速与恢复生效；未实测覆盖“已有120 rpm时进入CONTACT_CONFIRM仍保持120”的新增分支。**

不能将CONTACT=0解释为“没有进入过接触候选”，也不能把这次测试说成关键分支已经通过。
最初仅看策略事件时曾说未进入CONTACT_CONFIRM；检查UART补充FSM后已更正。
8秒rundown超时是原过程限时，不是本次新增独立保护故障；没有延时、强制CONTACT或加重制动来制造通过。

没有制动器电气时间戳或力矩真值，也没有同条件OFF对照，不能据此宣称负载抑制或拧紧质量改善。
运行末次STATUS的UDROP=0；停机查询突发后的STATUS出现UDROP=150，未将稀疏UART当成完整逐周期记录。
RAM中132条全轮趋势记录和策略事件已保存，记录覆盖检查通过。

## 关断与B恢复

用户明确确认12 V关闭、制动器释放后，执行：
`tmp/dob-load-contact-restore-1792846887484786700.json`，PASS。

- metadata序号1258，确认槽B，无待试运行；B应用仍为227964 B／CRC627317606。
- B／boot／配置未变，B应用未运行，motor_commands=0。
- VTOR=0x08040000，SD=0、MOE/PWM关闭，MCU暂停在B入口。

数据：`.trend.csv`、`.events.csv`、`.loadspeed.json`、Flash和RAM均与运行记录同名前缀。
分析：`tmp/dob-load-contact-board-analysis-20261024.json`。
曲线：`tmp/dob-load-contact-run-1792846770893941900.board.png`。
实际使用的板测脚本／解码／入口测试快照：`tmp/dob-load-contact-board-evidence-20261024`。

后续若需要验证新增保持分支，仍需安排受控、可释放的接触条件；本轮不自动重复，不为了覆盖分支提高负载或延长制动。
