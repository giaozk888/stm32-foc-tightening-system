# AW0 / SB3 关闭单次空载对照（2026-10-20）

结论：保持 AW1、240 rpm、原 PI/限幅/保护，仅不执行 SB3 后，本次稳速观察明显改善。相同 START 后 2.0～7.9 秒稀疏 STATUS 窗口，平均从 206.61 rpm 提高到 236.99 rpm，观察范围从 153.6～230.4 缩至 205.8～244.5 rpm。支持“SB3 是该工况下掉速的重要因素”，但仍是单次对照、非同步高频实验，不能证明所有残余波动都由 SB3 引起或已满足工业稳定性。

## 配置和流程

- 用户确认 12 V 关闭、MCU供电、空载固定、现场可断电；随后确认“开了，无”，电源保持 12 V / 限流 0.5 A。
- 新 A `Tightening240rpmAwNoSb3Candidate`，BIN SHA256 `d3fa11b83686b2b31c551088fdcf2d0a9872fbfd0fb50a52190075a31ecf291a`。
- 只写非活动 A 并完整比对、独立回读；原 B756、bootloader、配置保留。
- 正常 bootloader 健康确认与自动复位至 A759，无强制确认。
- 板端 PROFILE=AW0、FILTER=100/40/25/3，240 rpm、±0.50 A、300 rpm 独立超速、1.6 V、20000°、8 秒 rundown、12 秒 lease 均核对不变。
- 只发一次 START=7831，无 SET/SAVE、强制 CONTACT、故障清除或重试。
- 原速度 PI、SB2 卸载/上升速率、AW 积分接纳、参考斜坡不变；关闭的只是额外 SB3 快速制动/积分跟踪分支。所有独立保护保留。

## 同窗口结果

| 指标 | AW1 / SB3 开启 | AW0 / SB3 关闭 |
| --- | ---: | ---: |
| START 后 2.0～7.9 s 运行点数 | 95 | 95 |
| 上述窗口平均 CTRL / rpm | 206.61 | 236.99 |
| 上述窗口观察最小 / rpm | 153.6 | 205.8 |
| 上述窗口观察最大 / rpm | 230.4 | 244.5 |
| 全运行最高观察 / rpm | 231.2 | 244.5 |
| 最后约 0.35 s 的 6 点均值 / rpm | 207.13 | 230.70 |
| 预设尾段 240±24 rpm 初筛 | 未通过 | 通过 |

同窗口平均误差约从 13.9% 降至 1.25%，但只是采样点均值、不是时间加权积分或全带宽速度误差。末段还有 221～231 rpm 的下跌，不能把 236.99 rpm 均值说成所有时刻都在 240 rpm 附近。

本次约 1.252 秒 CTRL=237.2 rpm，随后多数点在 230～244 rpm。6.176 秒观察到最高 244.5 rpm，未触发原 300 rpm 独立超速。低频日志有 REF=240、CTRL=237.7、IqRef=162 mA、Iq=159 mA、Id=59 mA；日志不是硬同步快照，不将单帧当作全周期电流平均或物理映射证明。

约 8.120 秒流程到原 RUNDOWN_TIMEOUT，CONTACT=0、BUSY=0、IqRef=0。流程快照净行程约 10302.221°（28.62 圈），未达 20000°。是空载未接触的 8000 ms 流程边界，不是保护故障；没有进入 TIGHTEN/HOLD/DONE/OK，不算完整拧紧验收。

## 校准、时序和保护

- 零点 valid=4000、reject=51、total=4055、max consecutive reject=1、offset U/V=1561/1563，PASS。
- FOC wall max=31.547059 µs，deadline miss=0。
- actual CCR commit=298703，late=0，min margin=13.794118 µs。
- CUR_CONFIRM：163 enter / 163 clear / 0 fault，max cycles=2、max elapsed=101 µs。
- CURRENT_INVALID 未触发，unresolved total=7、max consecutive=1；suspect=1351、confirmed spike=1317、transition=34。这是算法标签，不证明物理毛刺成因。
- MOTOR TEST FAULT VALID=0、FLAGS=0；终止快照 domain=PROCESS、reason=RUNDOWN_TIMEOUT。
- encoder valid=1、errors=0；共模 plans=301454、adjusted=0、rejected=0、min slack=130 ticks，未覆盖实际共模平移。
- 没有额外修改参数或接入 S-curve。

## 收据与最终恢复

- 暂存：`tmp/aw-no-sb3-fsm-stage-1792467574342869800.json`。
- 运行：`tmp/aw-no-sb3-fsm-run-1792467627757706000.json`；`pass_=false` 代表空载流程未完成成功拧紧，不是未运行或保护故障。
- 运行全 Flash SHA256：`c06b7c151f76e95854d1aa9bfff63401260fbac6a8c67cc323e653c505510aa4`。
- 用户关闭 12 V 后恢复：`tmp/aw-no-sb3-fsm-restore-1792467697057236000.json`，PASS。
- 原 B 已选中/确认，generation=760，无 pending/attempt；SD=0、MOE=0、CCER=0，MCU halted 于 B 应用入口，B 应用未运行。
- 恢复全 Flash SHA256：`c373de5908ae867c41f3abb69bf0116fabfb9cd39cba14d399bc2a3063d56a78`。
- 恢复时 A/B 应用、bootloader、私有配置未变，仅正常启动元数据改变。原始 Flash/RAM 保留本地忽略目录，不公开私有数据。
