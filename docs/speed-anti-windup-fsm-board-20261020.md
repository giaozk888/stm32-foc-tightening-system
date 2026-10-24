# AW1 单次空载状态机对照（2026-10-20）

结论：AW1 已真实运行，约 8 秒到原 rundown 超时边界停止；无 CURRENT_INVALID、过流、编码器或 deadline/CCR late 保护故障。速度仍有反复下跌，未稳定跟踪 240 rpm，因此不据此接入 S-curve，也不宣称 anti-windup 已解决稳速问题。

## 固定条件与身份

- 用户确认 12 V 关闭、MCU 供电、工件/负载脱开、电机空载固定、人在现场可断电；随后确认上电且无报警。电源 12 V / 限流 0.5 A。
- 新 A：`Tightening240rpmSpeedAntiWindupCandidate`，BIN SHA256 `d1c7a791540c51c4aa9967cb5202a488514f6d47a1ff43321a50c80a9c90bc6a`。
- 仅写非活动 A 并独立回读通过，原 B752/bootloader/私有配置保留。正常 bootloader 健康确认与自动复位至 A755，无强制确认。
- 板端 PROFILE 两次核对 `SPEED_CTRL=AW1`；FILTER=100/40/25/3，原 CM=85、240 rpm、±0.50 A、300 rpm 边界、20000°、8000 ms rundown、12 秒 lease 不变。
- 只发一次 START=7831，无 SET/SAVE、强制 CONTACT 或自动重试。板测脚本 8 项离线契约测试通过。
- 本轮未再修改固件；S-curve 未实现/接入。

## 运动与对照

| 项目 | 原 SB3 100/40 空载 | 新 AW1 本次 |
| --- | ---: | ---: |
| 观察最高 CTRL / rpm | 226.6 | 231.2 |
| 最后约 0.35 秒的 6 点均值 / rpm | 203.42 | 207.13 |
| 240±24 rpm 尾段跟踪判据 | 未通过 | 未通过 |
| 流程终点 | 原 8 秒 TIMEOUT | 原 8 秒 TIMEOUT |
| CURRENT_INVALID | 无 | 无 |

两次均为稀疏 STATUS，一次对一次且初始转子位置等未严格控制；最高值和尾段均值的小幅提高不能证明重复性改善，更不能证明差异就是 anti-windup 所致。

本次约 0.567 秒 CTRL=89.1 rpm、IqRef=-204 mA，仍可见启动时的原 SB3 制动；1.001 秒 CTRL=164.3 rpm，约 1.06 秒已进入 RUNDOWN/ARMED；随后反复在约 160～230 rpm 区间变化。7.962 秒观察 CTRL=231.2 rpm、IqRef=-27 mA；8.022 秒仍 BUSY=1，CTRL=168.6 rpm。约 8.120 秒 STATUS 已显示 TIMEOUT、BUSY=0，IqRef=0。

流程停止快照净行程约 8954.123°（24.87 圈），未达到 20000°，终止原因是 8000 ms rundown 时间边界。空载 CONTACT=0，无 TIGHTEN/HOLD/OK，不把流程超时当作电流保护停机，也不当作完整拧紧成功。

低频日志出现 Iq/Id 波动，未保存连续完整 P/I/积分接纳与 limiter 同周期窗口；不能直接证明积分在何帧被阻止、速度回落来自哪一环节或物理电流是否跟踪。不能只凭这次最高速度决定开始 S-curve。

## 校准、时序与保护

- 校准 valid=4000、reject=41、total=4045、max consecutive reject=1，zero U/V=1560/1563，PASS。
- FOC wall max=31.611765 µs，deadline miss=0。
- actual CCR commit=298693，late=0，min margin=15.152941 µs。
- CUR_CONFIRM：135 enter / 135 clear / 0 fault，max cycles=2，max elapsed=101 µs。
- 停止快照：suspect=1276、confirmed spike=1235、transition=40、unresolved total=2、max consecutive=1。算法分类不是物理毛刺来源证明。
- MOTOR TEST FAULT VALID=0、FLAGS=0；流程快照 first_fault 属于 PROCESS / RUNDOWN_TIMEOUT，而非保护域。
- encoder valid=1、errors=0；共模 plans=301526、adjusted=0、rejected=0、min slack=130 ticks，没有覆盖真实共模平移。

## 收据与最终状态

- 暂存：`tmp/speed-anti-windup-fsm-stage-1792466667271081900.json`。
- 运行：`tmp/speed-anti-windup-fsm-run-1792466725334014300.json`。脚本 `pass_=false` 指空载终点不是成功拧紧，不代表未发 START 或时序失败。
- 运行全 Flash SHA256：`97c188d12f484ef5a0f5e5e5da799ee0e5eb8a9eb44fdf4596df1e40bb885b20`。
- 用户关闭 12 V 后恢复：`tmp/speed-anti-windup-fsm-restore-1792466792083378600.json`，PASS。
- 已选中/确认原 B，generation=756，无 pending/attempt；MCU halted 于 B 应用入口，B 应用未运行。
- SD=0、MOE=0、CCER=0。恢复时 A/B 应用、bootloader、私有配置未变，只更新正常启动元数据。
- 恢复全 Flash SHA256：`091b56601f18c416004358f6f8e43b1938f3652ec80729d798969eafdbe5753a`。
- 原始 Flash/RAM 保留本地忽略目录，不公开私有字节。
