# 100/40 候选单次自然接触状态机实测（2026-10-20）

本次在用户确认固定工件自然接触、固定与防护、现场可断电后，只执行一次原 START。板端约 7.1 秒报告 `EVT REQ=7831 COMPLETE RESULT=OK`，记录到了建立运动、接触确认、四档电流阶段、保持和 DONE 后回 IDLE。无保护故障。本结论仅是流程和电流指令链运行，不是螺钉扭矩或工业精度认证。

## 不变部分

- 同一份 `Tightening240rpmAdc100Return40Candidate` A，BIN SHA256 `a1e158f50c3809c96d9df39f3c52353a2ed4b50bb02e911a4824437e25da5cdd`，本轮没有刷写应用。
- 12 V、限流 0.5 A；240 rpm，速度环动态 Iq 上限 ±0.50 A，300 rpm 超速边界。
- JUMP=100、RETURN=40、CONFIRM=25、unresolved limit=3，板端读取核实。
- 20000°、rundown 8000 ms、板端 12 秒 lease、主机最后停止窗口 11.95 秒。
- 接触原判据：已建立运动、速度降至阈值（至多 10 rpm）、Iq demand 至少 0.30 A、连续 250 ms；未强制 CONTACT。
- 原 seating/T1/T2/T3/HOLD 为 80/100/120/150/150 mA，时间为 300/300/300/300/500 ms；直接 Iq 上限 0.20 A，扭矩阶段速度边界 30 rpm、接触后行程边界 90°。
- PI、相序、电角零点、FOC、PWM pipeline、CUR_CONFIRM、保护及 A/B 逻辑没有修改。没有 SET/SAVE、自动重试或第二个 START。

## 一次运行的证据

| START 后约 / s | 记录 |
| --- | --- |
| 0.087 | RUNDOWN_START，IqRef=32 mA |
| 约 1.3 | RUNDOWN，RUNDOWN_ARMED=1 |
| 4.832 | CTRL=25.8 rpm、DET=94.6 rpm，IqRef=500 mA，正在减速 |
| 4.896–5.076 | 速度接近零，IqRef=500 mA，形成持续负载条件 |
| 5.121 | CONTACT_CONFIRM，CONTACT_CONFIRMED=1，先用 neutral 等待稳定 |
| 5.375 | TIGHTEN seating，80 mA |
| 5.680 | T1，100 mA |
| 5.989 | T2，120 mA |
| 6.293 | T3，150 mA |
| 6.547 | HOLD，150 mA |
| 约 7.1 | `COMPLETE RESULT=OK`；随后 STATUS 的 FSM 为 IDLE、PREV_STATE=DONE，IqRef=0 |

接触前位置约 4249°，后续静止在约 4246°。记录的是编码器角度，不能直接换算为螺钉实际扭矩或紧固质量。稀疏 STATUS 最高 CTRL=222.1 rpm，不是完整波形峰值。

一条后段低频日志显示 IqRef=150 mA、Iq=192 mA、Id=9 mA；仅为一帧，不能作为各阶段电流跟踪均值。原继承 speed_summary 的尾段包含 IQ/HOLD 阶段，不能用尾段约零转速判定 240 rpm 跟踪失败或成功。

## 时序、保护与校准

- 零点：valid=4000、reject=33、total=4035、max consecutive reject=1、zero U/V=1559/1563，PASS。
- FOC wall max=31.605882 µs，deadline miss=0。
- actual CCR commit=278294，late=0，min margin=13.517647 µs。
- CUR_CONFIRM：149 enter / 149 clear / 0 fault，max cycles=2、max elapsed=101 µs。
- MOTOR TEST FAULT VALID=0、FLAGS=0；同镜像 RAM 的 first_fault.valid=0。没有 CURRENT_INVALID、超速或其他保护停机证据。
- 共模 plans=279905、adjusted=0、rejected=0、min slack=134 ticks，未覆盖实际共模平移。

## 脚本初始误报与离线核对

原判读器错误要求最终一次 STATUS 仍为 CONTACT=1 且正好观测到 DONE。然而现有固件在完成后回到 IDLE：最终 `OUTCOME=OK`、`CONTACT=0`，补充事件为 `FSM_STATE=IDLE PREV_STATE=DONE`，并不是接触从未成立。

原运行收据保留 `pass_=false` 和原始错误，不篡改历史结果。只修改测试脚本的离线判读器：需要当前 START 对应的有序 RUNDOWN_START/RUNDOWN/已确认 CONTACT_CONFIRM/TIGHTEN/HOLD、匹配请求的 COMPLETE OK，以及 DONE 或 IDLE/PREV_STATE=DONE 证据。不能只凭 legacy OUTCOME=OK 放行。

7 项脚本回归通过，包含本次真实已保存收据的离线核对；没有再次启动硬件。正式固件未改。没有扭矩仪，`torque_accuracy_verified=false`。

## 收据与最终恢复

- 断电核验：`tmp/adc100-return40-contact-inspect-1792462438122528000.json`，全 Flash 与 B748 基线相同，独立回读通过，无应用编程或激活。
- 运行：`tmp/adc100-return40-contact-run-1792462486181991600.json`，只发一次 START=7831，正常健康确认至 A751。
- 运行全 Flash SHA256：`00677322b7b1f88b400cd25d1860f32aba074d3bcb3819bb15e558f5cd14ad11`。
- 用户关闭 12 V 后恢复：`tmp/adc100-return40-contact-restore-1792462563420710100.json`，PASS。
- 原 B 已选中/确认，generation=752，无 pending/attempt；停在 B 应用入口，B 应用未运行。
- SD=0、MOE=0、CCER=0，MCU halted。恢复时 A/B 应用、bootloader、私有配置未变，只改变正常启动元数据。
- 恢复全 Flash SHA256：`4df90e1d414b7106d8215761c1f82780e8805d6e954090928514fc0b8dfba442`。
- 原始 Flash/RAM 留在本地忽略目录，不公开私有数据。
