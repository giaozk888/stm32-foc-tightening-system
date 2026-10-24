# 240 rpm / ±0.50 A 状态机自然结束实测

结论：当前配置确实已接入原 START → intent FSM → 原速度环/FOC，本次建立运动并进入 RUNDOWN，没有两秒提前 STOP。约 START 后 3.47 秒达到原 3000° 行程上限后自然终止。现有代码将 rundown 时间超限和行程超限统一报告为 TIMEOUT，因此 UART 显示 RUNDOWN_TIMEOUT；本次不是 8 秒计时到期。

空载 CONTACT=0，未进入 TIGHTEN/HOLD/DONE，也未返回 OK。不能说已验收真实完整拧紧或扭矩精度。240 rpm 稳速仍有波动，不因运行更久而改判通过。

## 条件与流程

用户本轮确认 12 V 关闭、MCU 供电、电机空载固定、信号及动力接线不变、人在现场可断电；随后回复已开启且无报警。电源沿用 12 V / 限流 0.5 A。

直接复用已保留的 A 镜像，BIN SHA256 `478715341f0b6e52e58a9a2c5ff818257369f4e0c82fa76a40d7bede0076443d`，本轮没有刷写应用固件。OFF 全 Flash 及独立回读通过；正常 bootloader 试运行、5 秒健康确认、自动复位完成至 A740，无强制确认。

- 目标 240 rpm，原参考斜坡 200 rpm/s。
- 速度环动态 Iq 上限 ±0.50 A；300 rpm 超速边界。
- 原 PI、电角零点、相序、采样、PWM pipeline、CUR_CONFIRM、current discriminator、硬过流、encoder/timing 保护不改。
- 原配方 RUNDOWN_TIMEOUT_MS=8000、MAX_TRAVEL_DEG=3000；post-contact 配方不改。
- 新脚本 `rundown240_fsm_board.py` 保留原板端 12 秒 lease、主机 11.95 秒最后停止窗口；本次自然结束先发生，主机没有提前两秒截断。
- 仅一次 START（request 7830），没有第二次 START、自动重试、SET 或 SAVE。

校准 valid=4000、reject=50、total=4050、max consecutive=1、offset U/V=1560/1563，PASS。预检 wall max=29.770 µs、deadline=0、actual CCR late=0、min margin=16.647 µs。

## 实测演化

| START 后主机时间 / s | CTRL / rpm | 机械位置 / ° | IqRef / A | 说明 |
| --- | --- | --- | --- | --- |
| 0.084 | 0.1 | 0.08 | +0.027 | RUNDOWN_START |
| 0.708 | 11.4 | 23.99 | +0.422 | 起转仍有间断 |
| 1.147 | 180.4 | 258.31 | +0.163 | RUNDOWN_ARMED=1，进入 RUNDOWN |
| 1.751 | 231.4 | 1018.38 | −0.028 | 运行日志观察到的 CTRL 峰值 |
| 2.001 | 213.8 | 1313.87 | +0.155 | 超过原两秒观察窗口继续运行 |
| 2.894 | 225.3 | 2427.91 | +0.175 | CONTACT 仍为 0 |
| 3.323 | 202.5 | 2936.27 | +0.131 | 最后一个 BUSY=1 的 STATUS |
| 3.467 | 202.5 | 3003.46 | 0 | 已自然 IDLE / RUNDOWN_TIMEOUT |

故障/流程停止快照实际位置 3001.201°，起始参考约 0.02197°，对应净行程约 3001.179°（8.34 圈）。不是把最后一个运行 STATUS 的 2936.19°净位移和终止快照混成同一时刻。

54 个运行 STATUS 观察 CTRL 范围 0.1..231.4 rpm，IqRef 范围 −0.056..+0.422 A。最后 0.35 秒左右的 6 个运行点平均 CTRL=199.42 rpm，未通过预先定义的稀疏 240±24 rpm 跟踪判据。采样间隔约 40–100 ms，这些最大值不是完整 20 kHz 波形峰值。

停机后 STATUS：IDLE、BUSY=0、OUTCOME=RUNDOWN_TIMEOUT、CONTACT=0、FLT=0、POS=3042.11°、CTRL=0.4 rpm、DET=0 rpm、IqRef=0。停机后的滑行位置不计作主动运行行程。

低频运行日志曾记录：REF=240 rpm、CTRL=202.4 rpm、IqRef=133 mA、Iq=148 mA、Id=19 mA。流程停止快照中 IqRef 已清零、Iq=171 mA，是停机附近的旧反馈，不可当成“运行中零指令却持续 171mA”的同步证据。

## 停止原因的代码证据

`firmware_common/tightening_intent_fsm.c` 在 RUNDOWN_START/RUNDOWN/未确认 CONTACT 阶段检查：

```c
elapsed(...) >= p->rundown_timeout_ms ||
fabsf(position - start_position) >= p->max_travel_deg
    -> fail(..., TF_REASON_TIMEOUT, ...)
```

本次主机时间约 3.47 秒，小于配方 8 秒，快照净行程大于 3000°，因此真实触发条件是行程。UART EVT 显示 OUTCOME=FAILED / FAULT_REASON=TIMEOUT、COMPLETE RESULT=TIMEOUT，与现有映射一致。该命名合并可能误导诊断，但本轮只测试配置，未擅自改枚举、状态机或阈值。

## 时序和保护

- FOC wall max：31.641176 µs；deadline miss=0。
- actual CCR commit=205084；late=0；min margin=15.164706 µs。
- CUR_CONFIRM：88 enter / 88 clear / 0 fault，max cycles=2、max elapsed=101 µs。
- MOTOR TEST FAULT VALID=0、FLAGS=0。流程快照 domain=PROCESS、legacy outcome reason=3，保护 flags=0；这是正常行程边界的失败结果，不是过流、encoder 或硬实时保护停机。
- 流程快照 encoder valid=1、errors=0；unresolved consecutive=0、max consecutive=2，未触发 CURRENT_INVALID。
- 共模 plans=207518、adjusted=0、rejected=0、min slack=140 ticks。本轮仍未覆盖真实共模平移，不能声称验证了此前不可行窗口的修复。

## 收据与最终恢复

- OFF 核验：`tmp/rundown240-fsm-inspect-1792458607469550400.json`。
- 单次运行：`tmp/rundown240-fsm-run-1792458781489542600.json`；最终运行 Flash SHA256 `ca9011199e3560ef2b778e14273eb50396e34d6aaa86e498763547197aa7d958`。
- 用户确认关闭 12 V 后，恢复：`tmp/rundown240-fsm-restore-1792458850455255600.json`。
- 恢复后选中/确认原 B，generation 741，停在 B 应用入口、B 应用未运行；SD=0、MOE=0、CCER=0、MCU halted。
- 恢复全 Flash SHA256 `d0f0b1dbb0e77df7a8dae773591720127f4c8143e533d10fad453296e437d663`。
- A/B 应用、bootloader、私有配置完整对比未变，只发生原 A/B 流程所需的启动元数据变化。原始 Flash/RAM 保留本地忽略目录，不公开私有字节。
