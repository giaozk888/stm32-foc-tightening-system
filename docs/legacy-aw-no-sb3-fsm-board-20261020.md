# L00：撤销新增 AW1 的单次空载对照（2026-10-20）

结论：两版都关闭 SB3、保留全部独立保护时，新 AW1 开/关的同窗口平均转速分别为 236.99 和 236.15 rpm，本次差异不足 1 rpm，未显示明确稳速优劣。不能据单次空载未明显饱和的结果认定 anti-windup 没有作用。

特别说明：本次不是“取消全部 anti-windup”。用户确认仅撤销新增 AW1 的部分边界积分接纳，保留历史条件积分、原 ±0.35 A 积分夹紧、SB2 积分卸载/上升速率；正常 PI 正负输出仍有效。

## 固定配置和流程

- A：`Tightening240rpmLegacyAwNoSb3Candidate`，BIN SHA256 `a17b269968b0e58bd7df9f2741ffe7552da5e971d5f9aa8a4f319439798d7324`。
- PROFILE 两次核对 `SPEED_CTRL=L00`，FILTER=100/40/25/3；AW1 调用与 SB3 Apply 均未编译进本控制路径。
- 用户确认断 12 V、MCU供电、空载固定、接线不变、现场可断电，随后开启电源且无报警；12 V / 限流 0.5 A。
- 240 rpm、速度 Iq 上限 ±0.50 A、300 rpm 独立超速、1.6 V 电压矢量限幅、20000°、8000 ms rundown、12 秒板端 lease 均不变。
- 只写非活动 A，独立回读与全 Flash 比对通过；B760、bootloader、私有配置保留。正常 bootloader 健康确认/复位至 A763，没有强制确认。
- 只发一次 START=7831，不 SET/SAVE、不强制 CONTACT、不清故障、不自动重试。
- 53 项定向回归通过（约 31.8 秒），包括撤销新增 AW1 的 4 项、板测脚本 8 项及既有 AW0/AW1/100-40/CUR_CONFIRM/零点/pipeline/FSM 测试。并非声明全部历史测试绿灯。

## 对照数据

| 指标 | AW0：新增 AW1 开、SB3 关 | L00：新增 AW1 关、SB3 关 |
| --- | ---: | ---: |
| START 后 2.0～7.9 s 点数 | 95 | 95 |
| 同窗口平均 CTRL / rpm | 236.99 | 236.15 |
| 同窗口观察范围 / rpm | 205.8～244.5 | 213.1～244.8 |
| 全运行观察最高 / rpm | 244.5 | 244.8 |
| 最后约 0.35 s 的 6 点均值 / rpm | 230.70 | 237.30 |
| 预设尾段 240±24 rpm 初筛 | 通过 | 通过 |

尾段均值看似提高而同窗口均值略低，正说明不能只截取某一小段就下结论。采样间隔约 40～100 ms，非同步高频测量；上述均值为采样点均值，不是全带宽或时间加权误差。初始转子位置等没有严格重复控制。当前证据支持“二者在此工况接近”，而不是“关掉所有防积分饱和会更好”。

本次约 1.126 秒 CTRL=214.1 rpm，后段多数在目标附近，但仍有局部下跌。约 8.136 秒已结束，OUTCOME=RUNDOWN_TIMEOUT、CONTACT=0、BUSY=0、IqRef=0。流程停止快照净行程约 10396.995°（28.88 圈），未达 20000°，是原 8 秒空载寻找接触超时，不是电流或超速保护故障。无 TIGHTEN/HOLD/DONE/OK，不是完整拧紧验收。

低频日志 REF=240、CTRL=241.7 rpm、IqRef=146 mA、Iq=134 mA、Id=11 mA 仅为单帧，且日志并非硬同步。未有连续 P/I/饱和状态窗口，不能声称已实机验证所有积分饱和恢复场景。

## 时序与保护

- 零点 valid=4000、reject=53、total=4055、max consecutive reject=1、offset U/V=1561/1563，PASS。
- FOC wall max=31.805882 µs，deadline miss=0。
- actual CCR commit=297903，late=0，min margin=14.370588 µs。
- CUR_CONFIRM：134 enter / 134 clear / 0 fault，max cycles=2、max elapsed=101 µs。
- CURRENT_INVALID 未触发，unresolved total=8、max consecutive=1；suspect=1279、confirmed spike=1243、transition=32。分类计数不能当作物理噪声成因证明。
- MOTOR TEST FAULT VALID=0、FLAGS=0；流程快照 domain=PROCESS、reason=RUNDOWN_TIMEOUT。
- encoder valid=1、errors=0；共模 plans=300329、adjusted=0、rejected=0、min slack=131 ticks，未覆盖实际共模平移。
- 未增加 S-curve、修改 PI/阈值或提高电流权限。

## 收据和最终状态

- 暂存：`tmp/legacy-aw-no-sb3-fsm-stage-1792468222958098300.json`。
- 运行：`tmp/legacy-aw-no-sb3-fsm-run-1792468286958655500.json`，主机 `pass_=false` 仅代表空载终点不是成功拧紧。
- 运行全 Flash SHA256：`bf94d60da3ad3b8a7333bc1a6bade8391bb6b7fb5314e61642dd694a46e46af4`。
- 用户关闭 12 V 后恢复：`tmp/legacy-aw-no-sb3-fsm-restore-1792468358062683600.json`，PASS。
- 原 B 已选中/确认，generation=764、无 pending/attempt；MCU halted 于 B 应用入口，B 应用未运行。
- SD=0、MOE=0、CCER=0。恢复时 A/B 应用、bootloader、私有配置未变，仅正常启动元数据改变。
- 恢复全 Flash SHA256：`676a10c74a792203be168ceeab14f362571be54da6dd60837127663eb6d66a98`。
- 原始 Flash/RAM 保留本地忽略目录，不公开私有字节。
