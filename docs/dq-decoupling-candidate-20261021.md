# candidate A：dq 交叉耦合补偿（离线候选）

暂停电流阶跃新旧 PI 对照，新增独立可开关的 dq 电感交叉项补偿。本轮没有连接调试器、串口、刷板、复位或启动电机；现场 B904 的启动选择未操作。

## 公式和范围

当前 Park：`Id = Ialpha*cos + Ibeta*sin`，`Iq = -Ialpha*sin + Ibeta*cos`。
复用现有 `encoder_omega_e_rad_s`，它由有符号机械控制速度乘 `2*pi/60 * POLE_PAIRS` 产生；极对数仍为 10，不能再乘一次极对数，也不使用 rpm 或速度指令代替电角速度。

```text
Vd_ff = -omega_e * Lq * Iq
Vq_ff = +omega_e * Ld * Id
Vd_raw = Vd_pi + Vd_ff
Vq_raw = Vq_pi + Vq_ff
(Vd,Vq) = 现有矢量电压限幅(Vd_raw,Vq_raw)
```

符号依据与代码一致的 [Microchip PMSM dq 电压方程 5.12](https://microchiptech.github.io/mcaf-doc/6.0.2/algorithms/foc/introduction.html#pmsm-voltage-equations)。没有可靠的永磁磁链参数，本轮**不添加** `omega_e*psi_m` 反电动势前馈，不加电阻前馈，不创建 observer，也不修改 Park/inverse Park。

暂用用户此前选择、但尚未通过正式辨识质量检查的 `Ld=20.03 µH`、`Lq=11.18 µH`。分别可用 `FOC_DQ_LD_H`、`FOC_DQ_LQ_H` 配置；这些仍是候选值，不是可信参数标定结果。240 rpm、10 极对、Iq=0.5 A 时，d 轴项约 -1.405 mV；Id=0 时 q 轴电感交叉项为 0。不要把它当成已经证明的起转故障修复。

## 接入位置与保护

- 只在 A 的正常、有效电流 PI 更新中计算，使用该帧的已准入 Id/Iq。discriminator 拒绝/hold 的调用路径、一拍 pending 和 ADC 入口 CCR commit 均未改。
- 位于 PI 输出后、原矢量电压限幅前。所有补偿经过原 1.60 V 总电压限幅，积分器仍限 ±0.75 V，不提高电流/速度/其他保护阈值。
- 饱和时原积分跟踪额外扣除对应 `Vd_ff/Vq_ff`，避免把总电压误当作 PI 电压而重复积分补偿。PI 增益、误差、积分更新顺序不变。这是补偿接入所需的跟踪调整，不是声称 PI 函数逐字未变。
- 非有限输入/补偿计算失败时调用现有 `ProtectedLoop_EmergencyOff(CL_BAD_OUTPUT)`，不吞异常。
- OFF 时连 `+0` 都不执行，回到原电压计算和积分跟踪，host 测试逐位比较 350 拍一致。
- current/speed PI 参数、速度/位置环、S-curve、加速度 FF、摩擦补偿、CUR_CONFIRM、TWO_SAMPLE、IRQ、PWM/ADC 频率、相序、电角零点、硬保护和 A/B 逻辑不改。

## 开关、证据与文件

构建默认不编译该功能：`FOC_DQ_DECOUPLING_CANDIDATE=OFF`。新增 A presets：

- `DqDecouplingCandidate`：继承正常 `CurrentPiIdentifiedCandidate`，编译补偿，RAM 默认 ON。
- `DqDecouplingOffCandidate`：同一功能集，RAM 默认 OFF。

不继承或继续运行此前的独占阶跃诊断。也没有将其专用的编码器放宽策略移植进正常闭环；这里继承的正常配置及其保护保持原样。

本地 UART 原协议命令（只在人工运行时使用，不会自行 START）：

```text
MOTOR TEST DQ OFF
MOTOR TEST DQ ON
MOTOR TEST DQ STATUS
MOTOR TEST DQ VOLTAGE
```

ON/OFF 只允许 IDLE、无启动/停止待处理、无 busy、SD/MOE/AOE/CCER 均关闭；运行期间拒绝切换。无远程控制扩权，仍经过原 LOCAL_CONSOLE_ONLY 路由。

ADC ISR 只更新一个 56 B 最新二进制帧，含 seq/source_us/ON、omega_e、Id/Iq、PI/FF/最终 Vdq、饱和和有效位；不 printf/UART、不新增历史 ring。任务命令短暂屏蔽中断取得一致副本，恢复原 PRIMASK 后才格式化。STATUS/VOLTAGE 是分开的最近帧查询，不保证两条命令读到同一 seq，也不是连续波形采集。reset/toggle 会清 valid；hold/fault 后可能保留上次有效帧，必须结合 seq、时间和原保护状态解读，不能把 valid 当成输出使能证明。命令应答保持协议文本，不增加新的高频文本日志或改已有 Pigweed 压缩配置。

修改文件：

- `firmware_common/foc_dq_decoupling.h`：纯数学、候选参数和帧结构。
- `firmware_common/foc_dq_decoupling_binding.inc`：本地空闲开关、任务层状态读取。
- `foc2_app_a/Core/Src/main.c`：PI 后接入、积分跟踪、最新帧发布及本地命令路由。
- `foc2_app_a/CMakeLists.txt`、`CMakePresets.json`：A-only opt-in、参数验证和 ON/OFF presets。
- `tests/test_foc_dq_decoupling.py`：实际 C PI 源码、数学、命令和冻结路径回归。

## 构建、测试、保留 B

| 构建 | FLASH B | RAM B | 结果 |
|---|---:|---:|---|
| A 原功能隔离重建 `DqBaselineUnchanged` | 217428 | 129160 | PASS |
| A `DqDecouplingCandidate` | 218724 | 129600 | PASS |
| A `DqDecouplingOffCandidate` | 218724 | 129600 | PASS |
| B 已有 `TighteningCommonModeTokenizedCandidate`，隔离目录 `DqBUnchanged` | 210540 | 128792 | PASS |

A 增加 FLASH 1296 B、RAM 440 B（包含热路径代码），静态 RAM 剩余 1408 B，后续不能无预算叠加诊断。此处 B 新构建验证的是已有 tokenized 配置，不等同于替换现场保存的 `FrictionBUnchanged`。

功能完全关闭的新 A 基线 BIN 与原 `CurrentPiIdentifiedCandidate` BIN SHA 均为：
`aaeee6b02372f9ecac2d8ec0ecb171f17bf87df41e54f43fe52b4ec9d404b56e`。

原保存 B BIN SHA 保持：
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`；B main/CMake/presets 均未修改。没有更改现场 Flash 或启动选择。

A ON/OFF 与新基线均为原 12 条 unused 警告及 1 条 RWX 链接警告，没有新增警告类别/错误。不是整个工程零警告。

新增 9 项测试通过；相关 pipeline、CUR_CONFIRM、timeout、编码器、S-curve、速度 FF、摩擦补偿和状态机等合计 68 项通过；另原电流 PI 5 项、阶跃 6 项通过，共 **79 项相关离线测试通过**，不是全仓库所有历史测试。关键日志：

- `tmp/dq-regression.log`（68）
- `tmp/dq-regression-pi.log`（5）
- `tmp/dq-regression-step.log`（6）
- `tmp/dq-build-on.log`、`dq-build-off.log`、`dq-build-baseline.log`、`dq-build-b.log`

测试包含正反电角速度、零速、Id/Iq 符号、非有限/溢出输入、OFF 逐位等价、统一电压饱和及 FF-aware 积分跟踪、真实本地命令的运行拒绝/空闲切换、原 pipeline/保护/角度/速度所有者不变。RL 交叉项抵消只是模型代数验证，不是电机实测性能。

## 后续人工板测步骤（本轮未执行）

1. 保持现场供电/接线/固定与防护检查，人工授权后按原 A/B 流程暂存新 A、完整回读、保留 B。不直接复用绑定旧 SHA 的阶跃脚本来刷本镜像。
2. 先校准和功率关闭时序预检，检查 FOC max、deadline miss、CCR late、实际 margin；本轮尚无新 FOC 时间，不能承诺仍为 28.88 µs 或必定 <50 µs。
3. 输出关闭、IDLE 时设置 DQ OFF，核对状态。人工做一次原受保护相同配方低速空载运行，记录 Id/Iq、速度/电压饱和、保护和时序；不要顺便改变 PI/摩擦/FF/速度配方。
4. 停止并确认输出关闭后再切 DQ ON，确认相同初始条件，人工做一次同样运行。比较 Id 交叉扰动、Iq 误差/过冲、速度跟踪及 CPU/CCR 余量。严禁运行中切换或自动升流。
5. 任一独立保护触发即退出，不自动重试/消故障；先前编码器超时根因未完成验证，本补偿不修复该故障。

dq 交叉耦合补偿候选已就绪，等待人工板测。

## 首次板测后的回复兼容修复

首次板测校准/输出关闭时序通过，但目标 nano printf 不支持新回复中的 `%f`，因此 **START=0**，未获得运动 OFF/ON 结果。已安全恢复 B908。

任务层回复现改为显式整数单位：电流 µA、电压 µV、速度 mrad/s、电感 nH。控制公式、PI 和二进制帧不变。修正版保留在独立 `DqDecouplingWireCandidate` / `DqDecouplingWireOffCandidate` 目录，FLASH 219300 B、RAM 129600 B；已编译、14 项相关离线回归通过，尚未刷入。原候选 BIN/ELF 作为已采集证据保留。

本次板测数据、根因、恢复状态及后续镜像身份见 `docs/dq-decoupling-board-20261021.md`。上文原 218724 B 构建和 79 项测试是首次候选记录，不是整数回复修正版的新板测结论。

后续修正版已完成一次人工 OFF/ON 空载对照：均达到约 240 rpm，无 deadline miss/真实 CCR late；改善并不全面，未升级 B。详见 `docs/dq-decoupling-off-on-board-20261021.md`；最终已恢复 B916 启动选择并停在入口。
