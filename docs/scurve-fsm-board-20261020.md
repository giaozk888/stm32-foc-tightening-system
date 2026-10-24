# SC1 S-curve + AW 单次空载上板对照（2026-10-20）

已完成一次原 START 状态机测试。电机建立运动，空载到原 8 秒 RUNDOWN_TIMEOUT，自然无 CONTACT/OK；不算真实拧紧或扭矩精度验收。全程保留全部独立保护，没有改 PI、阈值、相序或电角零点，没有自动重试。

## 本次运行与回退

用户确认 12 V 关闭、MCU 供电、电机空载固定、12 V/0.5 A、接线不变且在现场后，仅更新非活动 A。SC1 BIN/ELF 固定身份见 [候选说明](speed-scurve-candidate-20261020.md)，AW 开启、SB3 关闭。独立完整回读通过，B764、bootloader、私有配置和启动元数据未变。

另行收到开启 12 V 和无报警确认后，经正常 bootloader trial / 5 秒健康窗 / 自动确认复位，进入确认 A767；校准、镜像 SC1/100-40、时序、栈和 RAM 配方预检通过，单次 START 请求 7831。保留 240 rpm、±0.50 A、1.6 V、300 rpm 独立超速、20000°、8 秒 rundown、12 秒 lease。没有 SET/SAVE 或强制 CONTACT。

约 8.08 秒观测到 RUNDOWN_TIMEOUT、BUSY=0，输出关闭并锁定，MCU 停住，完整 Flash/RAM 已保存。原始收据 `pass_=false` 保留，因为“空载超时”不是“拧紧成功”；不是电流、编码器或时序保护故障。

用户重新确认 12 V 关闭后，通过原 bootloader 命令恢复 B768，无 pending/attempt，停在 B Reset_Handler（0x08051028）之前，B 应用未执行；SD=0、MOE=0、CCER=0。未再次 START。

## 测得结果

- 零点 PASS：4000 valid、42 reject、4045 total、最大连续 reject=1，zero U/V=1561/1564。total 含现有窗口填充点，不能简单以 valid+reject 代替。
- STATUS 共 129 个运行观测，最高 filtered/control speed **245.6 rpm**；首次观测到 >=240 rpm 约 **1.614 秒**。这是稀疏软件速度，不是全采样实际轴速峰值。
- 最后 6 个运行 STATUS 平均 **239.93 rpm**，通过原尾段 ±10% 初筛，但不能据尾段单独宣称整段稳速改善。
- 运行观测净行程约 9986.65°（27.74 圈）；停止后位置约 10089.55°。空载未触及 20000°，由 8 秒 rundown 时间结束。
- STATUS IqRef 最小 −22 mA、最大 284 mA、均值约 160.06 mA；末尾 32 个外环帧均值 IqRef≈0.16857 A、Iq≈0.16552 A、Id≈0.00640 A。末尾电流不能代表整段电流跟踪。
- FOC wall max **31.5294 µs**，>50 µs deadline miss **0**。
- actual CCR commit **299092**，late **0**，最小 actual margin **15.1353 µs**。
- CUR_CONFIRM **142 enter / 142 clear / 0 fault**，最大 2 cycles、101 µs。
- TWO_SAMPLE unresolved 合计 7、最大连续 1；未触发 CURRENT_INVALID。保护 flags=0，STATUS FLT=0。

## 同窗口比较

各自原始 STATUS 取 2～7.9 秒、BUSY=1，均 95 点；未挑选有利尾段或改窗口。

| 指标 | 线性 AW0（AW开，SB3关） | 线性 L00（新AW关，SB3关） | SC1（S-curve，AW开，SB3关） |
| --- | ---: | ---: | ---: |
| 平均 rpm | 236.99 | 236.15 | 233.12 |
| 最低 rpm | 205.8 | 213.1 | 191.2 |
| 最高 rpm | 244.5 | 244.8 | 245.2 |
| 标准差 rpm | 7.49 | 6.02 | 9.92 |
| 平均绝对误差 rpm | 4.77 | 4.69 | 7.24 |
| ±10% 内观测占比 | 95.79% | 97.89% | 92.63% |

本轮 SC1 全窗口平均更低、波动更大，尾段虽然接近 240 rpm，但**没有证明 S-curve 带来更好的稳速**。每个配置仅一次、传感器和外部工况未独立复现，不能仅凭此唯一归因于 S-curve。S-curve 主要用于参考加速度/jerk 约束，不自动消除原有电机/估速/跟踪掉速。不做额外 PI、限流、阈值调整。

## 参考轨迹证据的范围

本镜像紧凑 STATUS 没有 REF 字段，`trajectory_summary.observations=0` 不是参考没有变化。板端 `cl_startup` 为 **2000 B schema-1**：滚动记录最后 32 个约 1 kHz 外环帧，总计 8000 次更新，不能恢复整个起步段。

最初使用 schema-2 诊断 decoder 时按尺寸校验拒绝，未强制误解码、未重跑电机；后使用对应 schema-1 离线解析，并核对同一运行的 BIN/ELF/Flash 身份。末尾能看到参考达到 240 rpm，但**0→240 rpm 参考约 1.4 秒目前只是代码/离线轨迹结果，不能声称本次已全程实测其 jerk 曲线**。首次 CTRL>=240 的 1.614 秒是反馈观测时间，不等于参考到达时间。

## 本地证据（不提交原始 Flash/RAM）

- stage：`tmp/scurve-fsm-stage-1792478419224746100.json`，PASS，独立完整回读。
- run：`tmp/scurve-fsm-run-1792478491388804100.json`，正常保留空载 TIMEOUT 结果。
- run Flash SHA256：`0c5c72a73524b827b297a5c16f0cf9a933754652509c913842385a74fe32e403`。
- run SRAM SHA256：`3a4e7c89a67a05d3a45dfa3283308c4b3b747a31123ac116e5935ae690f5cb27`。
- file-only report：`tmp/scurve-fsm-analysis-1792478491388804100.json`。
- restore：`tmp/scurve-fsm-restore-1792478567684378200.json`，PASS，B768，应用未运行。
- restore Flash SHA256：`8db047e4bdfa7e5698a48b85587a68ef992f42ad9f54c3de4521c347df3881cc`。

新增 `tools/scurve_fsm_board.py` 固定 SC1 与 B764 基线，9 项无设备/模拟故障契约通过；`tools/scurve_fsm_report.py` 只分析已保存文件，4 项身份/布局/同窗口测试通过。没有改控制固件或重编译替换此次镜像。原始收据不回写成“成功”，旧 AW0/L00 收据保持不变。

本次已停止并关闭 12 V、恢复原 B 启动选择，不再启动电机。
