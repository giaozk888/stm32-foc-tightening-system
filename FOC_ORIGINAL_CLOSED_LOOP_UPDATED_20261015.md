# 原闭环逻辑＋当前数值配置

已生成独立的 `OriginalClosedLoopUpdated` A/B 镜像。它保留正常 `START → RUNDOWN → CONTACT_STOP → SEATING → T1/T2/T3 → HOLD → STOP/故障` 控制路径，不再使用刚才那个仍报告 2 A 的历史 BIN。

参数生成阶段没有操作板子。随后已按用户“关闭了／继续”的请求，仅写入非活动 B 槽并独立完整回读；没有激活、修改板上 KVS 或启动电机。上次历史版实测失败不能作为本版验收结果。

## 数值与边界

| 项目 | 新镜像实际配置 |
| --- | --- |
| 软件相电流保护阈值 | 4.0 A，保留故障锁存和关桥动作 |
| PWM 工况零点相对静态零点的准入偏差 | 100 个 ADC 计数 |
| 电流环周期 | 50 µs，即 20 kHz；不是已测执行耗时 |
| 速度环 Iq 指令限幅 | ±0.40 A，不变 |
| 直接 Iq 指令限幅 | ±0.15 A，不变 |
| 电压矢量／积分限幅 | 0.80 V／0.75 V，不变 |
| 电流 PI | Kp=0.080，Ki=188.0，不变 |
| 速度 PI | Kp=0.0030，Ki=0.0200，不变 |
| 运行采样与筛选 | 原双 ADC 同步注入路径、原跳变拒绝＋三点中值；未混入另一配置的四点筛选 |
| PWM 工况零点 | 当前源码的三点中值零点原语，4000 个有效样本；保留失败处理 |

4 A 是保护判据，不是允许电机按 4 A 给定运行，也不代替外部电源限流。未修改转速、PI、拧紧配方、参数持久化 ABI 或驱动板硬件保护。已有 KVS 配方仍按原逻辑加载，不会因为新 BIN 自动覆盖保存的参数。

“原闭环”是指保留正常控制路径，按当前源码重编译；不是声称与 10 月 8 日二进制仅差某一个字节。历史 BIN 保留原 SHA，不修改或改名冒充新版。

## 防止再次用错镜像

两槽新增同名独立 CMake preset，继承 `RouterTransferReadOnly`，而不是 `ProtectedCompactClosedLoop` 的单次 `MOTOR TEST` 入口。CMake 明确拒绝将此正常控制配置与硬关闭诊断、仅观察过流、取消零点配额、自适应实验、CAN FD 实验或远端电机服务混用。

启动身份从实际控制宏生成，例如：

```text
CONTROL PROFILE: ORIGINAL_UPDATED_20261015 TRIP_MA=4000 ZERO_DELTA=100 LOOP_US=50 SPEED_IQ_MA=400 DIRECT_IQ_MA=150 VOLTAGE_MV=800 FILTER=LEGACY_STEP_MEDIAN START=ORIGINAL QUALIFIED=0
```

这是预期输出格式，已在主机用两槽真实宏编译验证；不是本次板端串口实测日志。身份输出在启动任务内，不加入 ADC ISR；缓冲静态分配，避免扩大启动任务栈。

## 固定产物

| 槽 | 路径 | BIN 字节 | RAM 链接占用 |
| --- | --- | ---: | ---: |
| A | `foc2_app_a/build/OriginalClosedLoopUpdated/foc2.bin` | 201264 | 107440 B |
| B | `foc2_app_b/build/OriginalClosedLoopUpdated/foc2.bin` | 200360 | 107416 B |

A SHA256：`78576806abe0da428ccf96669c9e6d3e6eb5dc2f456f5bb25280a10f44d87e91`。

B SHA256：`78eb75ceb4bb87c256af67e3081ad4300dda98cecf2a016386539cc46b22cfe7`。

原历史 B：`foc2_app_b/build/PoweredSpeedBounded20261008/foc2.bin`，SHA256 仍为 `8b57f03e359f532338361b5fa8e53540d4afa829bb3acf3793e24f0b9b9a604c`。旧 `original_closed_loop_stage.py`／`original_closed_loop_trial.py` 固定此历史 SHA，不能用于本版；后续刷写必须先核验真实活动槽／非活动槽，再固定本版镜像和新基线。

## 离线结果

A/B configure、编译与链接通过。保留既有未使用函数／变量等警告，没有用关闭警告替代修复。

51 项 Python 测试通过：

- 新配置 5 项：两槽继承与编译定义、12 种错误混配拒绝、两槽真实宏的报告格式及截断行为、链接镜像身份和向量、历史 BIN 哈希保留。
- 相电流保护 5 项：4 A 边界、正负三相含重构 W、故障锁存／关桥、指令及电压限幅未扩张。
- 中值零点接入 5 项；零点校准门禁 7 项。
- 拧紧软件模型 29 项：接触持续判定、各阶段限流、超时／行程／停机、无工件不能冒充扭矩合格等。

这些是离线配置、源码、编译和模型验证，不是带电闭环、WCET 或扭矩精度验收。启动健康确认、保护、故障快照与限时实测仍应保留；不为获得通过而强制确认或清除故障。

## 本次板端暂存与回读

已确认驱动板 12 V 关闭。首次只读检查：VTOR=0x08008000、CPU 已暂停、SD=0、MOE/AOE=0、CCER=0；原 A 的采样计时器仍配置运行。完整 Flash 备份确认正常已确认槽为 A，元数据代数 540、无待试运行槽，A 镜像哈希与保留的回退产物一致。

随后只写 B（0x08040000 起，200360 字节），不写启动邮箱、不提交试运行、不发 START。过程中 OpenOCD 的 `verify_image` 芯片内 CRC 算法报 `not halted (start target algo)`／`error executing cortex_m crc algorithm`；调试器仍继续完成了后续写入。因此该操作回执保留为失败，未假装成正常校验成功，也未重刷。

对刷后已保存的全 Flash 比较通过后，另开一次**纯读取**会话，重新完整回读 512 KiB，再逐字节比对：

- B 的全部 200360 字节与本页固定新版镜像一致，SHA256 为 `78eb75ceb4bb87c256af67e3081ad4300dda98cecf2a016386539cc46b22cfe7`。
- B 槽外全部字节不变：包括 A、bootloader、KVS、参数和启动元数据；元数据仍为已确认 A540、无 pending。
- 最终 CPU 在 bootloader 复位暂停状态，VTOR=0、SD=0、MOE/AOE=0、CCER=0、TIM1 CEN=0；**新版 B 尚未激活，电机没有启动**。

新版暂存脚本已移除会在芯片上执行 CRC 算法的 `verify_image`，改成完整读取和主机字节比较；此次没有重新执行刷写。新增暂存门禁 5 项离线测试通过（加上参数配置 5 项复跑通过）。

证据均保存在既有受限目录，不公开 Flash 原始内容：

- 刷前检查：`safety_backups/protected-closed-loop-20261014/original-updated-1792049742928831300.json`。
- 含校验错误的原始刷写回执：`safety_backups/protected-closed-loop-20261014/original-updated-1792049819195370800.json`（保留失败标记）。
- 独立只读回读成功回执：`safety_backups/protected-closed-loop-20261014/original-updated-readback-1792049945637214400.json`。

这仅证明镜像写入与槽外保留，不代表启动校准、健康确认、20 kHz 执行耗时或电机闭环已经通过。后续试运行应固定本版哈希及本次回读基线，不能调用固定旧 2 A BIN 的历史脚本。

## 新版一次闭环短测尝试：启动阶段未通过

用户要求完成闭环电机测试，并确认 U/V/W 已接回、空载固定、12 V 开启、无报警且可立即断电。沿用电源 0.5 A 限流设置。新脚本离线门禁 4 项通过，然后仅提交一次正常 START_TRIAL；计划在正常健康确认后执行 20 rpm、最多 0.4 秒的 START/STOP。

实际结果：

- 静态零点 U/V=1560/1560；PWM 工况零点=1562/1561，均校准成功。
- 串口实际报告 `ORIGINAL_UPDATED_20261015 TRIP_MA=4000 ZERO_DELTA=100 ... FILTER=LEGACY_STEP_MEDIAN START=ORIGINAL QUALIFIED=0`，排除了误用旧 2 A 镜像。
- B 启动电流环后发生相电流保护 `REASON=1`。此时 `CONFIRMED=A PENDING=B ATTEMPTS=1 GEN=542 HOK=0`、`START_REQ=0`；**未发送 START，没有执行计划中的运动短测，更没有完成拧紧或扭矩精度验收**。
- 最终调试器停住 B，SD=0、MOE/AOE=0、CCER=0、TIM1 CEN=0。不复位、不清故障、不重试。A 回退镜像保留，但不能说已回退到 A。

在 B 保持暂停时，按本版 ELF 的符号地址只读首个保护快照（结构 80 B，连同相电流及故障原因共 96 B），不恢复运行：

| 项目 | 本次快照 |
| --- | --- |
| 首次保护时刻／ADC 序号 | 2688 ms／10773 |
| 保护所用 U/V ADC（已过旧跳变拒绝＋三点中值） | 2158／1096 |
| 最新物理 U/V ADC | 2172／1081 |
| 校准零点 U/V | 1562／1561 |
| 软件换算 U/V/W | -4.002／+3.122／+0.879 A |
| 中值缓存 U | 2138、2158、2172 |
| 中值缓存 V | 1096、1102、1081 |
| 筛选启用／缓存长度 | 1／3 |
| 接受／拒绝样本数 | 789／8 |

故障前保留的控制状态：Id_ref=Iq_ref=0；Id≈4.150 A、Iq≈-0.514 A；Vd≈-0.796 V、Vq≈0.078 V，电压矢量已接近 0.80 V 限幅；d/q 积分约 -0.464／+0.037 V。它们是停机后保留的最后状态，不等同于硬件实测电流或同一拍的完整轨迹。此时后台母线诊断尚无有效样本，不能据此报告实际母线电压为零。

结论：不是“筛选没开启”，也不是单个孤立尖峰被直接用于此次保护——两个中值缓存中三个值都明显偏离零点。当前证据表明零给定启动时反馈/电流环未能保持零电流，不能靠再提高保护阈值判为通过。电流反馈极性、相序/采样映射、编码器电角度映射和 PI 响应是待核查项，尚不能仅凭 ADC 换算确定真实相电流或唯一根因。

回执：

- `safety_backups/protected-closed-loop-20261014/original-updated-trial-1792050408479011700.json`。
- `safety_backups/protected-closed-loop-20261014/original-updated-fault-1792050539502429000.json`（首快照）。
- `safety_backups/protected-closed-loop-20261014/original-updated-fault-1792050597184623200.json`（同一已冻结快照，补充 PI 状态）。
