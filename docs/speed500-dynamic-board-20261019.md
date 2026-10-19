# SPEED 动态 Iq、±0.50 A 候选：2026-10-19

本次按用户澄清，不再执行 0.08/0.10/0.12/0.15/0.15 A 固定拧紧阶段。
独立候选只运行原 SPEED PI：目标 +20 rpm，最多 5 秒，IdRef=0，Iq 动态生成。
这不是完整拧紧、带载扭矩或工业精度验收。

## 代码范围

- 新增默认关闭的 `FOC_SPEED_DYNAMIC_DIAG`；A/B preset 为 `Speed500mADynamicDiagnostic`。
- 仅该候选的 `MOTOR_SPEED_IQ_LIMIT_A` 从 0.40 改为 0.50 A；正式默认仍为 0.40 A。
- 直接 IQ 模式限幅仍为 0.20 A。未修改速度/电流 PI、积分限幅、相序、电角零点、原配方、保护判据或频率。
- 复用现有任务级、每启动一次的诊断 admission。仅本地精确命令 `MOTOR TEST SPEED500 CONFIRM` 可提交；普通 START、固定 Iq 命令不能启动本诊断。
- admission 在门极使能前设置 SPEED=20 rpm，随后原 1 kHz 速度 PI 工作。
- 诊断 TighteningTask 不进入固定电流状态机阶段；原正式状态机不受影响。
- 继续使用原独立 5 秒 session lease、STOP、故障关断及一拍 PWM pipeline。禁止 ACK 不明后重发。
- schema-2 二进制 trace 仍为 32 帧，任务级每 200 ms 记录，另有终止帧；没有在 ADC ISR 增加打印。

## 编译与离线验证

| 构建 | Flash | RAM | BIN SHA-256 |
|---|---:|---:|---|
| A | 222028 B | 129928 B | `36d55fa46846a1d5f613f35e7c3fd95d115f66ee6f822bfa21c35971a9225001` |
| B | 221004 B | 129912 B | `dff94ecabde4411f882b19fc338774a6a05fc617a33c4281c60a11df43022a45` |

A ELF SHA-256：`c46cfd1b88968fa4bc57938a5576d831a4581c46e7aa346743f8b5e6e3b20036`。

相关回归 91 项通过：新 SPEED500 7、原 torque-chain 44、breakaway 40。
执行真实 C owner 的 -O2/-Os 测试，覆盖 fresh encoder、一次性 admission、STOP、故障、规划期间 STOP/故障竞态、拒绝固定 Iq 命令。
预处理函数比较确认：控制/保护路径只在 SPEED 的电流输出限幅常量处改变；ADC timing 与 IRQ 对象字节一致。
构建仍有基线已有的 unused 和 RWX 链接警告；未声称全仓测试或零警告。

## 刷写与实测收据

用户分别确认 12 V 关闭，以及上电 12 V/0.5 A、无报警、空载固定、可立即断电。

- 暂存：`tmp/speed500-stage-1792389989635109200.json`
  - 原 A696 故障现场已保存；经现有 mailbox 恢复 B697，停在 B 应用入口前。
  - reset/halt 后只刷非活动 A；两次完整回读通过，B、bootloader、私有配置未变。
  - 未使用已隔离的 no-reset Flash loader。
- 实测：`tmp/speed500-run-1792390072855831300.json`
  - 正常 A/B 试运行、健康确认复位后 A700；零点/采样/时序预检通过。
  - 精确 SPEED500 命令只发一次，实际受控运行 `5000007 us`，随后独立 lease 正常关闭输出。
  - 同次 Flash SHA-256：`f459f5be527b98b70d44362e48520e38296e421eae1ec29bf51c25b8aa42739f`。
  - 同名 `-flash.bin` 与 `-ram.bin` 为匹配 A ELF 的本地现场，不上传。
- 断电恢复：`tmp/speed500-restore-1792390190622648900.json`
  - 用户关断 12 V 后，仅经现有 mailbox 恢复原 B 启动选择，metadata generation=701。
  - B 应用未运行，MCU 停在入口，SD=0、MOE/AOE=0、CCER=0。
  - 所有应用与私有 Flash 内容保持；没有继续运动或自动重试。

## 实测结果：执行通过，速度跟踪未通过

| 项目 | 同次测量 |
|---|---:|
| 有效零点样本 | 4000 |
| 零点 reject / total | 55 / 4055 |
| 最大连续 reject | 1 |
| zero U/V | 1560 / 1563 |
| FOC wall max | 28.81765 us |
| >50 us | 0 |
| actual CCR commit | 248369 |
| actual CCR late | 0 |
| actual min margin | 5.13529 us |
| CUR_CONFIRM enter / clear / fault | 137 / 137 / 0 |
| 运行保护故障 | 无 |

25 个驱动中任务快照的 IqRef 从约 0 到正/负制动输出动态变化，最高记录值约 0.41041 A；记录到的 Iq 平均约 0.25430 A，Id 平均约 -0.00247 A。
这些是 200 ms 抽样统计，不是全部 20 kHz 样本的峰值/均值，也不能独立证明物理相电流或实际转矩。

软件速度诊断的整个运行窗口 extrema 保存在同次 SRAM：
`speed_diag_max_rpm=44.56604`，`speed_diag_min_rpm=-0.97791`，累计约 5.00078 s。
200 ms 快照只捕获到 16.003 rpm 峰值，不能用它替代全窗口 extrema。
没有独立测速仪验证这个瞬时软件峰值。

运动仍为间歇性：约 1 s 与 2.2 s 附近出现突发运动，4.8 s 时位置约 +39.02°；后半段位置基本不再增加，未稳定跟踪 20 rpm。
因此脚本 PASS 仅表示一次受保护测试正常完成、时序和停机检查通过，**不表示速度闭环性能通过**。

## 为什么上限 0.50 A，但记录主要到 0.41 A

本轮按要求保留旧 PI 参数：`SPEED_KP_A_PER_RPM=0.003`、`SPEED_INT_LIMIT_A=0.35`。
目标 20 rpm、反馈接近 0 时，未计制动约束的 PI 需求约为：

`0.003 * 20 + 0.35 = 0.41 A`。

0.50 A 是最终输出限幅，不是固定给定；仅抬这个上限不会自动产生 0.50 A。
未额外提高积分上限、速度 PI、保护阈值或电压限幅。
本次结果不能证明“0.50 A 仍带不动”，也不能单凭软件 dq 跟踪确认摩擦或电角度是根因。

结论：小固定 Iq 档位已从本次试验中排除，动态速度环试验与安全停机完成；断续起转/速度突发仍未解决，未自动更改其他参数。
