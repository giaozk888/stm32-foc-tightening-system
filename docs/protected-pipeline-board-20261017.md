# 保留保护的 pipeline 闭环候选：实机验收进度

## 当前结果

已完成一次候选 A 试运行、正常健康确认、30 秒功率关闭计算观察和一次原 START 闭环短测。**时序检查通过，闭环短测未通过**：START 后 `CUR_CONFIRM` 预算耗尽触发保护；未自动重试。

暂存时用户回复驱动板 12 V 已关闭。随后明确确认 U/V/W 接回、电机空载固定、12 V／限流 0.5 A、无报警且可立即断电，才执行本次单次试运行。结束后用户回复“关了”，已恢复原 B619 启动选择并停在入口，SD/MOE/CCER/TIM1 全关。

## 暂存证据

- 使用新 `pipeline_closed_loop_board_test.py`，默认离线；新增 6 项 host 门禁测试通过。
- 仅复用旧工具的全 Flash／擦除页／回退比较事务，不复用硬关闭镜像的试运行准入或 SRAM 解码。
- 候选 A：228940 字节，BIN SHA256 `b4d2368220699e6cf792b0a7032c52e3c74cb112351133363f97bcc4706cdd3e`。
- ELF SHA256 `5172cdd735e6152a3c9af38d5c1fd6840152d076f8b2388c1d0ee60fdb635477`。
- 基线为原 B615 恢复收据，完整 Flash SHA256 `270e1e887551c61cdc9826e242b017dfb66a6d86c7353a0780f9f2c9f00cbc2b`。
- 暂存收据：`safety_backups/protected-closed-loop-20261014/protected-pipeline-stage-1792228083458375300.json`，`pass_=true`。
- 写入后完整 Flash SHA256 `e273a6aa28ac8da8a0e9337b9a9f715c2679ae1af1f604d365bcfed963a6b719`。
- A 镜像和最后擦除页尾部正确；A 擦除页之外全部字节未变，原 B、bootloader、参数及元数据未变，confirmed B／generation 615。
- 最终 VTOR=0，DHCSR=0x30003，SD=0、BDTR=0、CCER=0，TIM1 已停止，CPU 停在 bootloader。
- 本轮无激活请求、无强制确认、无 START、无自动重试。

复用事务的控制台仍含历史 `B576`／`deferred shadow` 标签；这些不是本轮镜像身份或代号。实际门禁比较的是显式 B615 基线和上述候选 BIN/ELF，收据中的 metadata 为 615。

完整 Flash 备份留在原有受限 private 目录，不公开上传。下一阶段必须使用本候选的启动／READY／真实 CCR 统计；不能将旧硬关闭镜像的实测时间当作本镜像结果。通过当前镜像启动与时序准入后，才可经原 START 做一次现有 20 rpm／最多 400 ms 短测；这不等于负载拧紧或扭矩精度验收。

## 本次实测

BIN/ELF 与暂存版本完全一致，固件未在本轮调整。独立试运行工具经 8 项离线门禁测试后执行；正常启动连续健康 5 秒、自动确认复位及同代号确认均通过，随后 30 秒 READY 观察通过，真实提交准入 `ADC COMMIT READY=1`。

| 指标 | 本次观测 |
| --- | ---: |
| FOC wall max | 4904 cycles = 28.84706 µs |
| normal path max | 4873 cycles = 28.66471 µs |
| >50 µs deadline miss | 0 |
| 实际 CCR 三写提交完成计数 | 676917 |
| 实际 CCR late / blocked / post unsafe | 0 / 0 / 0 |
| 实际最小 margin | 2036 ticks = 11.97647 µs |
| 中性值提交准入计数 | 1000（固件饱和计数） |
| CUR_CONFIRM enter / clear / fault | 264 / 263 / 1 |
| CUR_CONFIRM max cycles / elapsed | 4 / 200 µs |

本候选 heavy profiling=0；没有采集 frames、IRQ 抢占 breakdown、重型 CCR 几何/写事务开销或 hypothetical 点明细。原始收据初版解码器错误展示这些未维护字段为 0，并因 frames=0 把 timing_pass 误标 false；已修正主机解码器及增加回归，不改变 MCU 镜像，不重跑硬件，另生成带来源哈希的派生分析收据。轻量固件的 `points` 在真实 CCR1/2/3 三写完成并通过末端检查后递增，因此本表使用它，不把重型 `writes=0` 当成未写 CCR 的证据。

## 原 START 与首故障

原 `motor_motion_smoke.py --execute --expected-slot A --target-rpm 20` 只调用一次，START 应答 `QUEUED`。只临时设置原有短测配方，最终逐项恢复原配方；未持久化参数、未改变保护阈值。第一条运动状态在主机 START 后约 85.1 ms 收到，已为 `OUTCOME=FAULT / REASON=9`；这个主机回报延迟不是精确的关断耗时。板端会话从 start_us=35134426 到首故障时刻约 35149843，约 15.417 ms。

同一镜像首故障快照：

- domain=2（protection），fault_reason=6（timeout），timeout_reason=3（CUR_CONFIRM）。
- `pending_since=35149643`，`now=35149843`，elapsed=200 µs，`limit_us=0`。0 表示按 ADC cycle 预算，不是零微秒超时。
- confirm 最大 4 cycles，fault=1；退出仍要求连续 2 个正常 raw safety sample。
- validator 当时 state=0、未处于 unresolved run；这不表示独立原码电流确认也已清除。
- 末端原码 IU/IV=1018/2166，零点 U0/V0=1564/1561。
- 当前指令 IqRef≈0.00864 A，计算反馈 Iq≈-1.753 A、Id≈4.118 A，过滤转速≈0.276 rpm，编码器 valid=1、errors=0。

因此本次失败是独立电流确认链未在 4 个新 ADC 周期内清除，不是 FOC 超时或实际 late-write；但这份快照不足以区分真实相电流、开关耦合或信号偏移，也没有故障前后连续电流窗口，不能将反馈数值直接认定为真实电流。电机尚未建立可验收的速度跟踪；不是扭矩精度或工业拧紧验收。

## 收尾及证据

先执行 STOP/ANALOG SAFE，再 SWD 关闭输出并 halt；故障不清除、不重试。用户关闭 12 V 后，经现有 bootloader mailbox 恢复原 B，不直接写 Flash 元数据，不执行 B 应用指令。

- 试运行原始收据：`protected-pipeline-trial-1792228438430412700.json`。
- 修正轻量解码的派生收据：`protected-pipeline-analysis-1792228764466524200.json`，保留原始收据及其 SHA256，candidate_pass=false、timing_pass=true。
- 恢复收据：`protected-pipeline-restore-1792228705413884300.json`，pass=true，confirmed B、pending none、attempts=0、generation=619。
- 最终完整 Flash SHA256：`1c0e575a570357145f77b299082360bc487c3309628e4261859ad7ad97cba46d`。
- A/B、bootloader 和配置字节在试运行／恢复期间未变；仅现有启动流程更新元数据。
- 最终 VTOR=0x08040000，DHCSR=0x30003、SD=0、BDTR=0、CCER=0，TIM1 停止，CPU 停在 B reset entry。
- 之后修正的主机 light 解码／恢复门禁合计 11 项测试通过，未修改任何控制算法或保护阈值。

本轮到此停止，不再次 START。
