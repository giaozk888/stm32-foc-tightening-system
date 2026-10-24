# 100/40 ADC 候选空载状态机实测（2026-10-20）

结论：一次 START 后电机实际运行约 8 秒，已建立运动并进入 RUNDOWN，最终因原 8 秒 rundown 时间上限返回 RUNDOWN_TIMEOUT。没有 CURRENT_INVALID、过流、编码器或 FOC deadline/CCR late 保护故障。空载 CONTACT=0，未进入 TIGHTEN/HOLD/DONE，不能认定完整拧紧验收通过；240 rpm 稳速仍未达标。

## 固定配置与执行

- A：`Tightening240rpmAdc100Return40Candidate`，BIN SHA256 `a1e158f50c3809c96d9df39f3c52353a2ed4b50bb02e911a4824437e25da5cdd`。
- 240 rpm，速度环 Iq 上限 ±0.50 A，超速边界 300 rpm；20000° 行程，rundown 8000 ms，板端 lease 12 秒。
- 12 V / 限流 0.5 A，电机空载固定；用户分别确认断电准备、供电、无报警以及测试后断电。
- 仅刷非活动 A，完整 Flash 比对与独立回读通过；B744、bootloader、私有配置保留。
- 正常 bootloader 试运行和 5 秒健康确认后自动复位至 A747，没有强制确认。
- 板端两次读取 FILTER，实际为 JUMP=100、RETURN=40、CONFIRM=25、UNRESOLVED_LIMIT=3。
- 校准 accepted=4000、reject=38、total=4040、max consecutive reject=1、offset U/V=1560/1563，PASS。滑动窗口初始化计数不要求 valid+reject=total。
- 脚本只发一次 START（7831），没有 SET/SAVE、强制 CONTACT 或自动重试。脚本 8 项离线契约测试通过。本轮未修改固件算法。

## 状态与运动

| 主机 START 后约 / s | CTRL rpm | 位置 ° | 说明 |
| --- | ---: | ---: | --- |
| 0.079 | 0.1 | 0.04 | RUNDOWN_START |
| 0.394 | 11.3 | 4.61 | 初始仍有断续 |
| 1.007 | 141.9 | 146.55 | 速度正在建立 |
| 1.256 | 208.5 | 394.49 | EVT：RUNDOWN_ARMED=1，进入 RUNDOWN |
| 4.740 | 226.6 | 4700.19 | 稀疏 STATUS 观察峰值，不是完整高速波形峰值 |
| 7.963 | 222.1 | 8655.05 | 最后一个 BUSY=1 的 STATUS |
| 8.077 | 226.1 | 8738.50 | TIMEOUT，BUSY=0、IqRef=0 |

流程停止快照位置 8735.914°，参考 -0.087891°，净行程约 8736.002°，即 24.27 圈，远未到 20000°。结合约 8 秒、EVT `TIMEOUT PREV_STATE=RUNDOWN`，本次是原 rundown 时间到期，不是行程上限或 TWO_SAMPLE 故障。

129 个运行 STATUS，观察最高 CTRL=226.6 rpm；最后约 0.35 秒的 6 点平均 203.42 rpm，未通过预设稀疏 240±24 rpm 尾段跟踪判据。状态回报间隔约 40–100 ms，不能把观察峰值当作真实瞬时最大速度。

一条低频运行日志：CMD/REF=240 rpm，CTRL=207.5 rpm，IqRef=171 mA，Iq=171 mA，Id=9 mA；仅是单帧同步证据，不是整个周期的均值。

## 判别与时序

- TWO_SAMPLE：suspect=1289，confirmed spike=1237，transition=49，unresolved total=5，max consecutive=1；未触发 CURRENT_INVALID。算法标签不是物理毛刺来源的证明，也不能仅凭这一次测试证明长期可靠性。
- CUR_CONFIRM：145 enter / 145 clear / 0 fault，max cycles=2，max elapsed=101 µs。
- FOC wall max=31.558824 µs，deadline miss=0。
- actual CCR commit=298698，late=0，min margin=15.141176 µs。
- MOTOR TEST FAULT VALID=0、FLAGS=0；流程停止快照 domain=PROCESS、reason=3，与 RUNDOWN_TIMEOUT 一致。
- 共模 plans=300718、adjusted=0、rejected=0，min slack=131 ticks；没有覆盖实际共模平移。
- `ADC TIMING` 的旧 LATE 字段不是 actual CCR late；真实 CCR 统计来自同镜像 RAM 快照，不混用。

## 收据和最终状态

- 暂存：`tmp/adc100-return40-fsm-stage-1792461797392853800.json`。
- 运行：`tmp/adc100-return40-fsm-run-1792461905613869100.json`。
- 运行全 Flash SHA256：`c6c42ec7de2ed7a8e5c870b0b6acdcf378dc77f2167d119a377208f3d70ea2b0`。
- 用户关闭 12 V 后恢复：`tmp/adc100-return40-fsm-restore-1792461987314022800.json`，PASS。
- 原 B 已选中/确认，generation=748，无 pending/attempt；MCU 停在 B 应用入口，B 应用未运行。
- SD=0、MOE=0、CCER=0，MCU halted；不再启动。
- 全 Flash SHA256：`ec0d003982a4ebd5aa44e860e85d694f6b6d1968e34f942b78c903bad43d3d0b`。
- A/B 应用、bootloader、私有配置未在恢复时改变，只更新正常启动元数据。原始 Flash/RAM 留在本地忽略目录，不公开私有数据。
